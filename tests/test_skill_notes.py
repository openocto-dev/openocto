"""Tests for the notes skill (wraps HistoryStore)."""

import pytest

from openocto.history import HistoryStore
from openocto.skills.base import SkillError
from openocto.skills.notes import NotesSkill


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "h.db"
    s = HistoryStore(db_path=db)
    yield s
    s.close()


@pytest.fixture
def skill(store):
    s = NotesSkill()
    uid = store.create_user("test", is_default=True)
    s.bind_context(history=store, user_id=uid, persona="octo")
    return s


class TestNotesSkill:
    async def test_unbound_raises(self):
        s = NotesSkill()
        with pytest.raises(SkillError):
            await s.execute(action="add_note", content="x")

    async def test_add_and_list_note(self, skill):
        result = await skill.execute(action="add_note", content="buy milk")
        assert "Saved note" in result

        listed = await skill.execute(action="list_notes")
        assert "buy milk" in listed

    async def test_add_note_requires_content(self, skill):
        with pytest.raises(SkillError):
            await skill.execute(action="add_note")

    async def test_add_and_list_fact(self, skill):
        result = await skill.execute(
            action="add_fact", content="prefers metric units", category="preference",
        )
        assert "Saved fact" in result
        assert "preference" in result

        listed = await skill.execute(action="list_facts")
        assert "prefers metric units" in listed

    async def test_resolve_note(self, skill, store):
        await skill.execute(action="add_note", content="todo")
        notes = store.get_active_notes(1, "octo")
        nid = notes[0]["id"]
        result = await skill.execute(action="resolve_note", note_id=nid)
        assert "Resolved" in result
        assert len(store.get_active_notes(1, "octo")) == 0

    async def test_resolve_requires_id(self, skill):
        with pytest.raises(SkillError):
            await skill.execute(action="resolve_note")

    async def test_unknown_action_raises(self, skill):
        with pytest.raises(SkillError):
            await skill.execute(action="dance")

    async def test_empty_lists(self, skill):
        notes = await skill.execute(action="list_notes")
        assert "No active notes" in notes
        facts = await skill.execute(action="list_facts")
        assert "No facts" in facts
