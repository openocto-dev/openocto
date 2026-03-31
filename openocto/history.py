"""SQLite-backed conversation history with multi-user support."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from openocto.config import USER_CONFIG_DIR

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = USER_CONFIG_DIR / "history.db"

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    pin        TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_identities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    provider    TEXT NOT NULL,
    external_id TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(provider, external_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    persona    TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    language   TEXT,
    backend    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_lookup
    ON messages(user_id, persona, created_at);
"""


class HistoryStore:
    """SQLite-backed conversation history with multi-user support."""

    def __init__(self, db_path: Path | None = None) -> None:
        path = db_path or _DEFAULT_DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        logger.info("History DB opened: %s", path)

    def close(self) -> None:
        self._conn.close()

    # ── Users ──────────────────────────────────────────────────────────

    def create_user(
        self, name: str, pin: str | None = None, is_default: bool = False,
    ) -> int:
        """Create a user and return their id."""
        cur = self._conn.execute(
            "INSERT INTO users (name, pin, is_default) VALUES (?, ?, ?)",
            (name, pin, int(is_default)),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_default_user(self) -> dict[str, Any] | None:
        """Return the default user (is_default=1), or None."""
        row = self._conn.execute(
            "SELECT * FROM users WHERE is_default = 1 LIMIT 1",
        ).fetchone()
        return dict(row) if row else None

    def get_last_active_user(self) -> dict[str, Any] | None:
        """Return the user with the most recent message, or None if no messages exist."""
        row = self._conn.execute(
            "SELECT u.* FROM users u "
            "JOIN messages m ON u.id = m.user_id "
            "ORDER BY m.id DESC LIMIT 1",
        ).fetchone()
        return dict(row) if row else None

    def get_user_by_name(self, name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE name = ? COLLATE NOCASE LIMIT 1",
            (name,),
        ).fetchone()
        return dict(row) if row else None

    def get_user_by_pin(self, pin: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE pin = ? LIMIT 1", (pin,),
        ).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, name, is_default FROM users ORDER BY id",
        ).fetchall()
        return [dict(r) for r in rows]

    # ── External identities ────────────────────────────────────────────

    def link_identity(
        self, user_id: int, provider: str, external_id: str,
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO user_identities (user_id, provider, external_id) "
            "VALUES (?, ?, ?)",
            (user_id, provider, external_id),
        )
        self._conn.commit()

    def get_user_by_identity(
        self, provider: str, external_id: str,
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT u.* FROM users u "
            "JOIN user_identities i ON u.id = i.user_id "
            "WHERE i.provider = ? AND i.external_id = ?",
            (provider, external_id),
        ).fetchone()
        return dict(row) if row else None

    # ── Messages ───────────────────────────────────────────────────────

    def add_message(
        self,
        user_id: int,
        persona: str,
        role: str,
        content: str,
        language: str | None = None,
        backend: str | None = None,
    ) -> int:
        """Append a message and return its id."""
        cur = self._conn.execute(
            "INSERT INTO messages (user_id, persona, role, content, language, backend) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, persona, role, content, language, backend),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_recent_messages(
        self, user_id: int, persona: str, limit: int = 20,
    ) -> list[dict[str, str]]:
        """Return last *limit* messages for user+persona, oldest-first.

        Returns dicts with 'role' and 'content' keys — ready for AI backends.
        """
        rows = self._conn.execute(
            "SELECT role, content FROM ("
            "  SELECT role, content, id FROM messages "
            "  WHERE user_id = ? AND persona = ? "
            "  ORDER BY id DESC LIMIT ?"
            ") sub ORDER BY id ASC",
            (user_id, persona, limit * 2),  # limit is in turns, *2 for messages
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def clear_history(
        self, user_id: int, persona: str | None = None,
    ) -> int:
        """Delete messages for a user. Returns count of deleted rows."""
        if persona:
            cur = self._conn.execute(
                "DELETE FROM messages WHERE user_id = ? AND persona = ?",
                (user_id, persona),
            )
        else:
            cur = self._conn.execute(
                "DELETE FROM messages WHERE user_id = ?", (user_id,),
            )
        self._conn.commit()
        return cur.rowcount
