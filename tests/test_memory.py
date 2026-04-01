"""Tests for the Memory system (MemoryManager + HistoryStore memory tables)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openocto.config import MemoryConfig
from openocto.history import HistoryStore
from openocto.memory import DEFAULT_SUMMARY_SECTIONS, MemoryManager
from openocto.persona.manager import Persona


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test_memory.db"
    s = HistoryStore(db_path=db_path)
    yield s
    s.close()


@pytest.fixture
def config():
    return MemoryConfig(
        recent_window=10,
        summarize_threshold=5,
        notes_ttl_days=14,
    )


@pytest.fixture
def persona():
    return Persona(
        name="octo",
        display_name="Octo",
        description="Test persona",
        system_prompt="You are Octo.",
    )


@pytest.fixture
def memory(store, config):
    return MemoryManager(store, config)


# ── HistoryStore: Summaries ────────────────────────────────────────────


class TestSummaries:
    def test_no_summary_initially(self, store):
        uid = store.create_user("Test")
        assert store.get_latest_summary(uid, "octo") is None

    def test_add_and_get_summary(self, store):
        uid = store.create_user("Test")
        sid = store.add_summary(uid, "octo", "Summary text", 1, 10, 10)
        assert sid > 0

        s = store.get_latest_summary(uid, "octo")
        assert s is not None
        assert s["summary"] == "Summary text"
        assert s["from_msg_id"] == 1
        assert s["to_msg_id"] == 10
        assert s["msg_count"] == 10

    def test_latest_summary_is_most_recent(self, store):
        uid = store.create_user("Test")
        store.add_summary(uid, "octo", "First", 1, 10, 10)
        store.add_summary(uid, "octo", "Second", 11, 20, 10)

        s = store.get_latest_summary(uid, "octo")
        assert s["summary"] == "Second"

    def test_summaries_per_persona(self, store):
        uid = store.create_user("Test")
        store.add_summary(uid, "octo", "Octo summary", 1, 10, 10)
        store.add_summary(uid, "hestia", "Hestia summary", 1, 10, 10)

        assert store.get_latest_summary(uid, "octo")["summary"] == "Octo summary"
        assert store.get_latest_summary(uid, "hestia")["summary"] == "Hestia summary"

    def test_count_unsummarized(self, store):
        uid = store.create_user("Test")
        for i in range(10):
            store.add_message(uid, "octo", "user", f"msg-{i}")

        assert store.count_unsummarized(uid, "octo") == 10

        # Add summary covering first 5 messages
        store.add_summary(uid, "octo", "Summary", 1, 5, 5)
        assert store.count_unsummarized(uid, "octo") == 5

    def test_get_unsummarized_messages(self, store):
        uid = store.create_user("Test")
        ids = []
        for i in range(10):
            ids.append(store.add_message(uid, "octo", "user", f"msg-{i}"))

        store.add_summary(uid, "octo", "Summary", ids[0], ids[4], 5)
        unsummarized = store.get_unsummarized_messages(uid, "octo")
        assert len(unsummarized) == 5
        assert unsummarized[0]["content"] == "msg-5"


# ── HistoryStore: Notes ────────────────────────────────────────────────


class TestNotes:
    def test_add_and_get_notes(self, store):
        uid = store.create_user("Test")
        nid = store.add_note(uid, "octo", "Discuss pilaf recipe", category="followup")
        assert nid > 0

        notes = store.get_active_notes(uid, "octo")
        assert len(notes) == 1
        assert notes[0]["note"] == "Discuss pilaf recipe"
        assert notes[0]["category"] == "followup"

    def test_resolve_note(self, store):
        uid = store.create_user("Test")
        nid = store.add_note(uid, "octo", "Some note")
        store.resolve_note(nid)

        notes = store.get_active_notes(uid, "octo")
        assert len(notes) == 0

    def test_auto_resolve_old_notes(self, store):
        uid = store.create_user("Test")
        # Insert a note with old timestamp manually
        store._conn.execute(
            "INSERT INTO conversation_notes (user_id, persona, note, is_active, created_at) "
            "VALUES (?, ?, ?, 1, datetime('now', '-30 days'))",
            (uid, "octo", "Old note"),
        )
        store._conn.execute(
            "INSERT INTO conversation_notes (user_id, persona, note, is_active, created_at) "
            "VALUES (?, ?, ?, 1, datetime('now'))",
            (uid, "octo", "Fresh note"),
        )
        store._conn.commit()

        resolved = store.auto_resolve_old_notes(uid, "octo", ttl_days=14)
        assert resolved == 1

        active = store.get_active_notes(uid, "octo")
        assert len(active) == 1
        assert active[0]["note"] == "Fresh note"

    def test_notes_per_persona(self, store):
        uid = store.create_user("Test")
        store.add_note(uid, "octo", "Octo note")
        store.add_note(uid, "hestia", "Hestia note")

        assert len(store.get_active_notes(uid, "octo")) == 1
        assert len(store.get_active_notes(uid, "hestia")) == 1

    def test_max_notes_respected(self, store):
        uid = store.create_user("Test")
        for i in range(25):
            store.add_note(uid, "octo", f"Note {i}")

        notes = store.get_active_notes(uid, "octo")
        assert len(notes) == 25  # DB stores all, MemoryManager limits


# ── HistoryStore: Facts ────────────────────────────────────────────────


class TestFacts:
    def test_add_and_get_facts(self, store):
        uid = store.create_user("Test")
        fid = store.add_fact(uid, "Name is Dmitry", category="personal")
        assert fid > 0

        facts = store.get_active_facts(uid)
        assert len(facts) == 1
        assert facts[0]["fact"] == "Name is Dmitry"
        assert facts[0]["category"] == "personal"

    def test_deactivate_fact(self, store):
        uid = store.create_user("Test")
        fid = store.add_fact(uid, "Lives in Moscow")
        store.deactivate_fact(fid)

        facts = store.get_active_facts(uid)
        assert len(facts) == 0

    def test_fact_categories(self, store):
        uid = store.create_user("Test")
        store.add_fact(uid, "Name is Dmitry", category="personal")
        store.add_fact(uid, "Prefers informal tone", category="communication_style")
        store.add_fact(uid, "Software developer", category="work")

        facts = store.get_active_facts(uid)
        assert len(facts) == 3
        categories = {f["category"] for f in facts}
        assert categories == {"personal", "communication_style", "work"}

    def test_facts_global_not_per_persona(self, store):
        uid = store.create_user("Test")
        store.add_fact(uid, "Name is Dmitry")

        facts = store.get_active_facts(uid)
        assert len(facts) == 1  # Facts are global (not filtered by persona)


# ── HistoryStore: FTS5 ─────────────────────────────────────────────────


class TestFTS:
    def test_fts_search_finds_messages(self, store):
        uid = store.create_user("Test")
        store.add_message(uid, "octo", "user", "How to cook borscht?")
        store.add_message(uid, "octo", "assistant", "Here is a borscht recipe")
        store.add_message(uid, "octo", "user", "What about pilaf?")

        results = store.fts_search("borscht", uid)
        assert len(results) >= 1
        contents = [r["content"] for r in results]
        assert any("borscht" in c.lower() for c in contents)

    def test_fts_search_empty_query(self, store):
        uid = store.create_user("Test")
        store.add_message(uid, "octo", "user", "Hello")
        assert store.fts_search("", uid) == []

    def test_fts_search_no_results(self, store):
        uid = store.create_user("Test")
        store.add_message(uid, "octo", "user", "Hello world")
        results = store.fts_search("quantum", uid)
        assert results == []

    def test_fts_search_per_user(self, store):
        uid1 = store.create_user("Alice")
        uid2 = store.create_user("Bob")
        store.add_message(uid1, "octo", "user", "I love cooking pasta")
        store.add_message(uid2, "octo", "user", "I love playing chess")

        results = store.fts_search("cooking", uid1)
        assert len(results) >= 1
        results2 = store.fts_search("cooking", uid2)
        assert len(results2) == 0


# ── MemoryManager: build_context ───────────────────────────────────────


class TestBuildContext:
    def test_basic_context_with_no_memory(self, memory, store, persona):
        uid = store.create_user("Test")
        store.add_message(uid, "octo", "user", "Hello")
        store.add_message(uid, "octo", "assistant", "Hi!")

        system_prompt, history = memory.build_context(uid, persona, "How are you?")

        assert "You are Octo." in system_prompt
        assert len(history) == 2
        assert history[0]["content"] == "Hello"

    def test_context_includes_facts(self, memory, store, persona):
        uid = store.create_user("Test")
        store.add_fact(uid, "Name is Dmitry", category="personal")
        store.add_message(uid, "octo", "user", "Hello")

        system_prompt, _ = memory.build_context(uid, persona, "Hi")

        assert "Name is Dmitry" in system_prompt
        assert "[personal]" in system_prompt

    def test_context_includes_notes(self, memory, store, persona):
        uid = store.create_user("Test")
        store.add_note(uid, "octo", "Discuss pilaf recipe next time")
        store.add_message(uid, "octo", "user", "Hello")

        system_prompt, _ = memory.build_context(uid, persona, "Hi")

        assert "Discuss pilaf recipe" in system_prompt
        assert "Active notes" in system_prompt

    def test_context_includes_summary(self, memory, store, persona):
        uid = store.create_user("Test")
        store.add_message(uid, "octo", "user", "Hello")
        store.add_summary(uid, "octo", "### Preferences\nLikes brief answers.", 1, 1, 1)

        system_prompt, _ = memory.build_context(uid, persona, "Hi")

        assert "Likes brief answers" in system_prompt
        assert "Previous conversation context" in system_prompt

    def test_recent_window_limits_messages(self, store, persona):
        config = MemoryConfig(recent_window=4)
        mem = MemoryManager(store, config)
        uid = store.create_user("Test")

        for i in range(20):
            store.add_message(uid, "octo", "user", f"msg-{i}")

        _, history = mem.build_context(uid, persona, "Hi")
        # recent_window=4 → get_recent_messages(limit=4)
        # limit is in turns → 4*2=8 messages
        assert len(history) == 8


# ── MemoryManager: parse_response ──────────────────────────────────────


class TestParseResponse:
    def test_parse_full_response(self, memory):
        text = """\
## SUMMARY
### Preferences
User likes short answers.
### Ongoing topics
Studying Python.

## NOTES
- Discuss pilaf recipe next time
- RESOLVED: Call mom

## FACTS
[personal] User's name is Dmitry
[communication_style] Prefers informal tone
[work] Software developer at Rocket Dev
"""
        summary, notes, resolved, facts = memory._parse_response(text)

        assert "User likes short answers" in summary
        assert "Studying Python" in summary
        assert len(notes) == 1
        assert "pilaf" in notes[0]
        assert len(resolved) == 1
        assert "Call mom" in resolved[0]
        assert len(facts) == 3
        assert facts[0] == ("personal", "User's name is Dmitry")
        assert facts[1] == ("communication_style", "Prefers informal tone")
        assert facts[2] == ("work", "Software developer at Rocket Dev")

    def test_parse_none_sections(self, memory):
        text = """\
## SUMMARY
Just chatting.

## NOTES
None

## FACTS
None
"""
        summary, notes, resolved, facts = memory._parse_response(text)
        assert summary == "Just chatting."
        assert notes == []
        assert resolved == []
        assert facts == []

    def test_parse_facts_without_category(self, memory):
        text = """\
## SUMMARY
Summary.

## NOTES
None

## FACTS
User has a cat named Barsik
"""
        _, _, _, facts = memory._parse_response(text)
        assert len(facts) == 1
        assert facts[0] == ("personal", "User has a cat named Barsik")


# ── MemoryManager: quality guard ───────────────────────────────────────


class TestQualityGuard:
    def test_short_summary_fails_for_many_messages(self, memory):
        assert not memory._validate_summary("Short.", 30)

    def test_short_summary_ok_for_few_messages(self, memory):
        assert memory._validate_summary("Short.", 5)

    def test_empty_summary_fails(self, memory):
        assert not memory._validate_summary("", 5)

    def test_good_summary_passes(self, memory):
        assert memory._validate_summary("A" * 100, 30)


# ── MemoryManager: facts similarity ───────────────────────────────────


class TestFactsSimilarity:
    def test_identical_facts(self):
        assert MemoryManager._facts_similar("User's name is Dmitry", "User's name is Dmitry")

    def test_case_insensitive(self):
        assert MemoryManager._facts_similar("User's name is Dmitry", "user's name is dmitry")

    def test_subset_match(self):
        assert MemoryManager._facts_similar("Name is Dmitry", "User's name is Dmitry")

    def test_different_facts(self):
        assert not MemoryManager._facts_similar("Name is Dmitry", "Has a cat")


# ── MemoryManager: summary sections from persona ──────────────────────


class TestSummarySections:
    def test_default_sections(self, memory, persona):
        sections = memory._get_summary_sections(persona)
        assert sections == DEFAULT_SUMMARY_SECTIONS

    def test_custom_sections_from_persona(self, memory):
        p = Persona(
            name="metis",
            display_name="Metis",
            description="Business persona",
            system_prompt="You are Metis.",
            memory_summary_sections=["Decisions", "Tasks", "Context"],
        )
        sections = memory._get_summary_sections(p)
        assert sections == ["Decisions", "Tasks", "Context"]


# ── MemoryManager: maybe_process trigger ───────────────────────────────


class TestMaybeProcess:
    @pytest.mark.asyncio
    async def test_no_processing_below_threshold(self, memory, store, persona):
        uid = store.create_user("Test")
        for i in range(10):
            store.add_message(uid, "octo", "user", f"msg-{i}")

        router = MagicMock()
        await memory.maybe_process(uid, persona, router)
        # Should not call AI — below threshold

    @pytest.mark.asyncio
    async def test_disabled_memory_skips(self, store, persona):
        config = MemoryConfig(enabled=False)
        mem = MemoryManager(store, config)
        uid = store.create_user("Test")

        router = MagicMock()
        await mem.maybe_process(uid, persona, router)
        # Should return immediately


# ── MemoryManager: update_facts dedup ──────────────────────────────────


class TestUpdateFacts:
    def test_new_fact_added(self, memory, store):
        uid = store.create_user("Test")
        memory._update_facts(uid, [("personal", "Name is Dmitry")])

        facts = store.get_active_facts(uid)
        assert len(facts) == 1
        assert facts[0]["fact"] == "Name is Dmitry"

    def test_duplicate_fact_skipped(self, memory, store):
        uid = store.create_user("Test")
        store.add_fact(uid, "Name is Dmitry", category="personal")
        memory._update_facts(uid, [("personal", "User's name is Dmitry")])

        facts = store.get_active_facts(uid)
        assert len(facts) == 1  # not duplicated

    def test_different_fact_added(self, memory, store):
        uid = store.create_user("Test")
        store.add_fact(uid, "Name is Dmitry", category="personal")
        memory._update_facts(uid, [("personal", "Has a cat")])

        facts = store.get_active_facts(uid)
        assert len(facts) == 2
