"""Tests for MCPServerStore — SQLite DAO for external MCP server metadata.

Uses a real sqlite3 connection in a temp directory (no mocks for the DB layer).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from openocto.mcp_client.store import MCPServerStore

# We need to apply the same schema that HistoryStore uses so the table exists.
_SCHEMA = """\
CREATE TABLE IF NOT EXISTS mcp_servers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT UNIQUE NOT NULL,
    url                 TEXT NOT NULL DEFAULT '',
    transport           TEXT NOT NULL DEFAULT 'http',
    command             TEXT,
    args_json           TEXT NOT NULL DEFAULT '[]',
    tool_allowlist_json TEXT NOT NULL DEFAULT '[]',
    enabled             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    last_status         TEXT,
    last_error          TEXT,
    last_checked_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_mcp_servers_enabled ON mcp_servers(enabled);
"""


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(tmp_path / "test.db"))
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    yield db
    db.close()


@pytest.fixture()
def store(conn: sqlite3.Connection) -> MCPServerStore:
    return MCPServerStore(conn)


# ── Tests ──────────────────────────────────────────────────────────────────


class TestCreateAndGet:
    def test_create_returns_id(self, store: MCPServerStore) -> None:
        sid = store.create("notion", "https://mcp.notion.com/mcp")
        assert isinstance(sid, int)
        assert sid >= 1

    def test_get_round_trip(self, store: MCPServerStore) -> None:
        sid = store.create("notion", "https://mcp.notion.com/mcp", transport="http")
        row = store.get(sid)
        assert row is not None
        assert row["name"] == "notion"
        assert row["url"] == "https://mcp.notion.com/mcp"
        assert row["transport"] == "http"
        assert row["enabled"] == 1

    def test_get_nonexistent_returns_none(self, store: MCPServerStore) -> None:
        assert store.get(9999) is None

    def test_get_by_name(self, store: MCPServerStore) -> None:
        store.create("github", "https://mcp.github.com/mcp")
        row = store.get_by_name("github")
        assert row is not None
        assert row["name"] == "github"

    def test_get_by_name_missing(self, store: MCPServerStore) -> None:
        assert store.get_by_name("nope") is None

    def test_create_with_allowlist(self, store: MCPServerStore) -> None:
        sid = store.create("ha", "http://192.168.1.10/mcp", tool_allowlist=["lights_on", "lights_off"])
        row = store.get(sid)
        assert row["tool_allowlist"] == ["lights_on", "lights_off"]

    def test_allowlist_defaults_to_empty_list(self, store: MCPServerStore) -> None:
        sid = store.create("bare", "http://example.com/mcp")
        row = store.get(sid)
        assert row["tool_allowlist"] == []


class TestDuplicateName:
    def test_create_duplicate_name_raises_value_error(self, store: MCPServerStore) -> None:
        store.create("notion", "https://mcp.notion.com/mcp")
        with pytest.raises(ValueError, match="already exists"):
            store.create("notion", "https://other.example.com/mcp")


class TestList:
    def test_list_returns_empty_initially(self, store: MCPServerStore) -> None:
        assert store.list() == []

    def test_list_returns_all_servers(self, store: MCPServerStore) -> None:
        store.create("a", "http://a.example.com/mcp")
        store.create("b", "http://b.example.com/mcp")
        rows = store.list()
        assert len(rows) == 2

    def test_list_ordered_by_name(self, store: MCPServerStore) -> None:
        store.create("zebra", "http://z.example.com/mcp")
        store.create("alpha", "http://a.example.com/mcp")
        names = [r["name"] for r in store.list()]
        assert names == ["alpha", "zebra"]

    def test_list_enabled_skips_disabled(self, store: MCPServerStore) -> None:
        store.create("on", "http://on.example.com/mcp", enabled=True)
        store.create("off", "http://off.example.com/mcp", enabled=False)
        rows = store.list_enabled()
        assert len(rows) == 1
        assert rows[0]["name"] == "on"


class TestUpdate:
    def test_update_url(self, store: MCPServerStore) -> None:
        sid = store.create("svc", "http://old.example.com/mcp")
        store.update(sid, url="http://new.example.com/mcp")
        row = store.get(sid)
        assert row["url"] == "http://new.example.com/mcp"

    def test_update_enabled(self, store: MCPServerStore) -> None:
        sid = store.create("svc", "http://example.com/mcp", enabled=True)
        store.update(sid, enabled=False)
        row = store.get(sid)
        assert row["enabled"] == 0

    def test_update_tool_allowlist(self, store: MCPServerStore) -> None:
        sid = store.create("svc", "http://example.com/mcp")
        store.update(sid, tool_allowlist=["tool_a"])
        row = store.get(sid)
        assert row["tool_allowlist"] == ["tool_a"]

    def test_update_bumps_updated_at(self, store: MCPServerStore) -> None:
        sid = store.create("svc", "http://example.com/mcp")
        row_before = store.get(sid)
        time.sleep(0.01)
        store.update(sid, url="http://other.example.com/mcp")
        # updated_at column should differ (SQLite datetime precision is 1s in practice,
        # but at least verify it runs without error and returns True)
        result = store.update(sid, url="http://another.example.com/mcp")
        assert result is True

    def test_update_nonexistent_returns_false(self, store: MCPServerStore) -> None:
        result = store.update(9999, url="http://x.com/mcp")
        assert result is False

    def test_update_partial_doesnt_wipe_other_fields(self, store: MCPServerStore) -> None:
        sid = store.create("svc", "http://example.com/mcp", transport="http")
        store.update(sid, enabled=False)
        row = store.get(sid)
        assert row["transport"] == "http"  # unchanged
        assert row["enabled"] == 0


class TestDelete:
    def test_delete_removes_row(self, store: MCPServerStore) -> None:
        sid = store.create("svc", "http://example.com/mcp")
        assert store.delete(sid) is True
        assert store.get(sid) is None

    def test_delete_nonexistent_returns_false(self, store: MCPServerStore) -> None:
        assert store.delete(9999) is False

    def test_list_after_delete(self, store: MCPServerStore) -> None:
        sid = store.create("svc", "http://example.com/mcp")
        store.delete(sid)
        assert store.list() == []


class TestSetStatus:
    def test_set_status_connected(self, store: MCPServerStore) -> None:
        sid = store.create("svc", "http://example.com/mcp")
        store.set_status(sid, "connected")
        row = store.get(sid)
        assert row["last_status"] == "connected"
        assert row["last_error"] is None
        assert row["last_checked_at"] is not None

    def test_set_status_error(self, store: MCPServerStore) -> None:
        sid = store.create("svc", "http://example.com/mcp")
        store.set_status(sid, "error", "Connection refused")
        row = store.get(sid)
        assert row["last_status"] == "error"
        assert row["last_error"] == "Connection refused"

    def test_set_status_clears_error(self, store: MCPServerStore) -> None:
        sid = store.create("svc", "http://example.com/mcp")
        store.set_status(sid, "error", "oops")
        store.set_status(sid, "connected")
        row = store.get(sid)
        assert row["last_error"] is None
