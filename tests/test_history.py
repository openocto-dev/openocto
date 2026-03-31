"""Tests for HistoryStore (SQLite-backed conversation history)."""

import pytest

from openocto.history import HistoryStore


@pytest.fixture
def store(tmp_path):
    """Create an in-memory HistoryStore for testing."""
    db_path = tmp_path / "test_history.db"
    s = HistoryStore(db_path=db_path)
    yield s
    s.close()


# ── User CRUD ──────────────────────────────────────────────────────────


class TestUsers:
    def test_create_and_get_default_user(self, store):
        uid = store.create_user("Dmitry", is_default=True)
        assert uid == 1

        user = store.get_default_user()
        assert user is not None
        assert user["name"] == "Dmitry"
        assert user["is_default"] == 1

    def test_no_default_user(self, store):
        assert store.get_default_user() is None

    def test_get_user_by_name(self, store):
        store.create_user("Alice")
        user = store.get_user_by_name("alice")  # case-insensitive
        assert user is not None
        assert user["name"] == "Alice"

    def test_get_user_by_name_not_found(self, store):
        assert store.get_user_by_name("nobody") is None

    def test_get_user_by_pin(self, store):
        store.create_user("Bob", pin="1234")
        user = store.get_user_by_pin("1234")
        assert user is not None
        assert user["name"] == "Bob"

    def test_get_user_by_pin_not_found(self, store):
        assert store.get_user_by_pin("9999") is None

    def test_list_users(self, store):
        store.create_user("Alice")
        store.create_user("Bob")
        users = store.list_users()
        assert len(users) == 2
        assert users[0]["name"] == "Alice"
        assert users[1]["name"] == "Bob"

    def test_list_users_empty(self, store):
        assert store.list_users() == []


    def test_get_last_active_user(self, store):
        uid1 = store.create_user("Alice")
        uid2 = store.create_user("Bob")
        store.add_message(uid1, "octo", "user", "hello")
        store.add_message(uid2, "octo", "user", "hi")  # Bob spoke last

        user = store.get_last_active_user()
        assert user is not None
        assert user["name"] == "Bob"

    def test_get_last_active_user_no_messages(self, store):
        store.create_user("Alice")
        assert store.get_last_active_user() is None


# ── External identities ───────────────────────────────────────────────


class TestIdentities:
    def test_link_and_lookup(self, store):
        uid = store.create_user("Dmitry")
        store.link_identity(uid, "telegram", "123456")

        user = store.get_user_by_identity("telegram", "123456")
        assert user is not None
        assert user["name"] == "Dmitry"

    def test_identity_not_found(self, store):
        assert store.get_user_by_identity("telegram", "000") is None

    def test_duplicate_identity_ignored(self, store):
        uid = store.create_user("Dmitry")
        store.link_identity(uid, "telegram", "123")
        store.link_identity(uid, "telegram", "123")  # should not raise

    def test_multiple_identities(self, store):
        uid = store.create_user("Dmitry")
        store.link_identity(uid, "telegram", "111")
        store.link_identity(uid, "mobile", "device-abc")

        assert store.get_user_by_identity("telegram", "111")["id"] == uid
        assert store.get_user_by_identity("mobile", "device-abc")["id"] == uid


# ── Messages ──────────────────────────────────────────────────────────


class TestMessages:
    def test_add_and_get_messages(self, store):
        uid = store.create_user("Dmitry")
        store.add_message(uid, "octo", "user", "Hello!")
        store.add_message(uid, "octo", "assistant", "Hi there!")

        msgs = store.get_recent_messages(uid, "octo")
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "Hello!"}
        assert msgs[1] == {"role": "assistant", "content": "Hi there!"}

    def test_messages_ordered_oldest_first(self, store):
        uid = store.create_user("Dmitry")
        for i in range(5):
            store.add_message(uid, "octo", "user", f"msg-{i}")

        msgs = store.get_recent_messages(uid, "octo")
        contents = [m["content"] for m in msgs]
        assert contents == ["msg-0", "msg-1", "msg-2", "msg-3", "msg-4"]

    def test_messages_limited(self, store):
        uid = store.create_user("Dmitry")
        for i in range(50):
            store.add_message(uid, "octo", "user", f"u-{i}")
            store.add_message(uid, "octo", "assistant", f"a-{i}")

        msgs = store.get_recent_messages(uid, "octo", limit=5)
        # limit=5 turns = 10 messages
        assert len(msgs) == 10
        # Should be the most recent 10
        assert msgs[0]["content"] == "u-45"
        assert msgs[-1]["content"] == "a-49"

    def test_messages_per_persona(self, store):
        uid = store.create_user("Dmitry")
        store.add_message(uid, "octo", "user", "Hello Octo")
        store.add_message(uid, "hestia", "user", "Hello Hestia")

        octo_msgs = store.get_recent_messages(uid, "octo")
        hestia_msgs = store.get_recent_messages(uid, "hestia")
        assert len(octo_msgs) == 1
        assert len(hestia_msgs) == 1
        assert octo_msgs[0]["content"] == "Hello Octo"
        assert hestia_msgs[0]["content"] == "Hello Hestia"

    def test_messages_per_user(self, store):
        uid1 = store.create_user("Alice")
        uid2 = store.create_user("Bob")
        store.add_message(uid1, "octo", "user", "I'm Alice")
        store.add_message(uid2, "octo", "user", "I'm Bob")

        alice_msgs = store.get_recent_messages(uid1, "octo")
        bob_msgs = store.get_recent_messages(uid2, "octo")
        assert len(alice_msgs) == 1
        assert alice_msgs[0]["content"] == "I'm Alice"
        assert len(bob_msgs) == 1
        assert bob_msgs[0]["content"] == "I'm Bob"

    def test_clear_history_all(self, store):
        uid = store.create_user("Dmitry")
        store.add_message(uid, "octo", "user", "msg1")
        store.add_message(uid, "hestia", "user", "msg2")

        deleted = store.clear_history(uid)
        assert deleted == 2
        assert store.get_recent_messages(uid, "octo") == []
        assert store.get_recent_messages(uid, "hestia") == []

    def test_clear_history_per_persona(self, store):
        uid = store.create_user("Dmitry")
        store.add_message(uid, "octo", "user", "msg1")
        store.add_message(uid, "hestia", "user", "msg2")

        deleted = store.clear_history(uid, persona="octo")
        assert deleted == 1
        assert store.get_recent_messages(uid, "octo") == []
        assert len(store.get_recent_messages(uid, "hestia")) == 1

    def test_empty_history(self, store):
        uid = store.create_user("Dmitry")
        assert store.get_recent_messages(uid, "octo") == []

    def test_add_message_returns_id(self, store):
        uid = store.create_user("Dmitry")
        mid1 = store.add_message(uid, "octo", "user", "first")
        mid2 = store.add_message(uid, "octo", "user", "second")
        assert mid2 > mid1

    def test_add_message_with_metadata(self, store):
        uid = store.create_user("Dmitry")
        store.add_message(uid, "octo", "user", "hello", language="ru")
        store.add_message(uid, "octo", "assistant", "hi", backend="claude")
        # Metadata is stored but not returned by get_recent_messages
        msgs = store.get_recent_messages(uid, "octo")
        assert len(msgs) == 2
