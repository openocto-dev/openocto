"""Tests for the SemanticSearch module (FTS5-based)."""

import pytest

from openocto.config import MemoryConfig
from openocto.history import HistoryStore
from openocto.search import SemanticSearch


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test_search.db"
    s = HistoryStore(db_path=db_path)
    yield s
    s.close()


@pytest.fixture
def config():
    return MemoryConfig(search_half_life_days=30)


@pytest.fixture
def search(store, config):
    return SemanticSearch(store, config)


class TestSemanticSearch:
    def test_search_empty_query(self, search, store):
        uid = store.create_user("Test")
        store.add_message(uid, "octo", "user", "Hello world")
        assert search.search("", uid) == []

    def test_search_finds_fts_results(self, search, store):
        uid = store.create_user("Test")
        store.add_message(uid, "octo", "user", "How to make borscht soup?")
        store.add_message(uid, "octo", "assistant", "Here is a borscht recipe for you")
        store.add_message(uid, "octo", "user", "Thanks! Now tell me about pilaf")

        results = search.search("borscht", uid, limit=3)
        assert len(results) >= 1
        assert any("borscht" in r["content"].lower() for r in results)

    def test_search_respects_limit(self, search, store):
        uid = store.create_user("Test")
        for i in range(20):
            store.add_message(uid, "octo", "user", f"borscht recipe variant {i}")

        results = search.search("borscht", uid, limit=3)
        assert len(results) <= 3

    def test_search_per_user(self, search, store):
        uid1 = store.create_user("Alice")
        uid2 = store.create_user("Bob")
        store.add_message(uid1, "octo", "user", "I love cooking pasta")
        store.add_message(uid2, "octo", "user", "I love playing chess")

        results = search.search("cooking", uid1)
        assert len(results) >= 1
        results2 = search.search("cooking", uid2)
        assert len(results2) == 0

    def test_search_no_results(self, search, store):
        uid = store.create_user("Test")
        store.add_message(uid, "octo", "user", "Hello world")

        results = search.search("quantum physics", uid)
        assert results == []

    def test_index_message_does_not_crash(self, search, store):
        uid = store.create_user("Test")
        msg_id = store.add_message(uid, "octo", "user", "Test message")
        # Should not raise even without vector dependencies
        search.index_message(msg_id, "Test message")


class TestTemporalDecay:
    def test_recent_message_high_decay(self, search):
        # A message from now should have decay close to 1.0
        from datetime import datetime
        now = datetime.now().isoformat()
        decay = search._temporal_decay(now)
        assert decay > 0.9

    def test_old_message_low_decay(self, search):
        # A message from 60 days ago with half-life=30 should be ~0.25
        from datetime import datetime, timedelta
        old = (datetime.now() - timedelta(days=60)).isoformat()
        decay = search._temporal_decay(old)
        assert 0.2 < decay < 0.3

    def test_empty_date_returns_one(self, search):
        assert search._temporal_decay("") == 1.0

    def test_invalid_date_returns_one(self, search):
        assert search._temporal_decay("not-a-date") == 1.0


class TestVectorAvailable:
    def test_vector_available_returns_bool(self):
        result = SemanticSearch.vector_available()
        assert isinstance(result, bool)
