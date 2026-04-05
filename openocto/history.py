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

CREATE TABLE IF NOT EXISTS conversation_summaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    persona     TEXT NOT NULL,
    summary     TEXT NOT NULL,
    from_msg_id INTEGER NOT NULL,
    to_msg_id   INTEGER NOT NULL,
    msg_count   INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_summaries_lookup
    ON conversation_summaries(user_id, persona, to_msg_id);

CREATE TABLE IF NOT EXISTS conversation_notes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    persona       TEXT NOT NULL,
    note          TEXT NOT NULL,
    category      TEXT DEFAULT 'general',
    source_msg_id INTEGER,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notes_lookup
    ON conversation_notes(user_id, persona, is_active);

CREATE TABLE IF NOT EXISTS user_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    fact       TEXT NOT NULL,
    category   TEXT DEFAULT 'personal',
    source     TEXT DEFAULT 'extracted',
    persona    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_facts_user
    ON user_facts(user_id, is_deleted);
"""

_FTS_SCHEMA = """\
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='id',
    tokenize='unicode61'
);
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
        self._init_fts()
        logger.info("History DB opened: %s", path)

    def _init_fts(self) -> None:
        """Create FTS5 virtual table if not exists."""
        try:
            self._conn.executescript(_FTS_SCHEMA)
        except sqlite3.OperationalError:
            logger.warning("FTS5 not available in this SQLite build, text search disabled")
            self._fts_available = False
            return
        self._fts_available = True

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

    def delete_user(self, user_id: int) -> None:
        """Delete a user and all their related data."""
        self._conn.execute("DELETE FROM user_facts WHERE user_id = ?", (user_id,))
        self._conn.execute("DELETE FROM conversation_notes WHERE user_id = ?", (user_id,))
        self._conn.execute("DELETE FROM conversation_summaries WHERE user_id = ?", (user_id,))
        self._conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        self._conn.execute("DELETE FROM user_identities WHERE user_id = ?", (user_id,))
        self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self._conn.commit()

    def set_default_user(self, user_id: int) -> None:
        """Set a user as default (clears default from all others)."""
        self._conn.execute("UPDATE users SET is_default = 0")
        self._conn.execute("UPDATE users SET is_default = 1 WHERE id = ?", (user_id,))
        self._conn.commit()

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
        msg_id = cur.lastrowid
        # Sync FTS5 index
        if self._fts_available:
            try:
                self._conn.execute(
                    "INSERT INTO messages_fts(rowid, content) VALUES (?, ?)",
                    (msg_id, content),
                )
            except sqlite3.OperationalError:
                pass  # FTS table may not exist
        self._conn.commit()
        return msg_id  # type: ignore[return-value]

    def get_recent_messages(
        self, user_id: int, persona: str, limit: int = 20,
    ) -> list[dict[str, str]]:
        """Return last *limit* messages for user+persona, oldest-first.

        Returns dicts with 'role' and 'content' keys — ready for AI backends.
        """
        rows = self._conn.execute(
            "SELECT role, content, created_at FROM ("
            "  SELECT role, content, created_at, id FROM messages "
            "  WHERE user_id = ? AND persona = ? "
            "  ORDER BY id DESC LIMIT ?"
            ") sub ORDER BY id ASC",
            (user_id, persona, limit * 2),  # limit is in turns, *2 for messages
        ).fetchall()
        return [{"role": r["role"], "content": r["content"], "created_at": r["created_at"]} for r in rows]

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

    # ── Conversation summaries ─────────────────────────────────────────

    def get_latest_summary(
        self, user_id: int, persona: str,
    ) -> dict[str, Any] | None:
        """Return the most recent summary for user+persona."""
        row = self._conn.execute(
            "SELECT * FROM conversation_summaries "
            "WHERE user_id = ? AND persona = ? "
            "ORDER BY to_msg_id DESC LIMIT 1",
            (user_id, persona),
        ).fetchone()
        return dict(row) if row else None

    def add_summary(
        self,
        user_id: int,
        persona: str,
        summary: str,
        from_msg_id: int,
        to_msg_id: int,
        msg_count: int,
    ) -> int:
        """Store a conversation summary. Returns its id."""
        cur = self._conn.execute(
            "INSERT INTO conversation_summaries "
            "(user_id, persona, summary, from_msg_id, to_msg_id, msg_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, persona, summary, from_msg_id, to_msg_id, msg_count),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_unsummarized_messages(
        self, user_id: int, persona: str, limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return messages after the last summary, oldest-first."""
        last = self.get_latest_summary(user_id, persona)
        after_id = last["to_msg_id"] if last else 0
        rows = self._conn.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE user_id = ? AND persona = ? AND id > ? "
            "ORDER BY id ASC LIMIT ?",
            (user_id, persona, after_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_unsummarized(self, user_id: int, persona: str) -> int:
        """Count messages after the last summary."""
        last = self.get_latest_summary(user_id, persona)
        after_id = last["to_msg_id"] if last else 0
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM messages "
            "WHERE user_id = ? AND persona = ? AND id > ?",
            (user_id, persona, after_id),
        ).fetchone()
        return row["cnt"]

    # ── Conversation notes ─────────────────────────────────────────────

    def get_active_notes(
        self, user_id: int, persona: str,
    ) -> list[dict[str, Any]]:
        """Return active notes for user+persona, newest-first."""
        rows = self._conn.execute(
            "SELECT * FROM conversation_notes "
            "WHERE user_id = ? AND persona = ? AND is_active = 1 "
            "ORDER BY created_at DESC",
            (user_id, persona),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_note(
        self,
        user_id: int,
        persona: str,
        note: str,
        category: str = "general",
        source_msg_id: int | None = None,
    ) -> int:
        """Add a conversation note. Returns its id."""
        cur = self._conn.execute(
            "INSERT INTO conversation_notes "
            "(user_id, persona, note, category, source_msg_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, persona, note, category, source_msg_id),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def resolve_note(self, note_id: int) -> None:
        """Mark a note as resolved (inactive)."""
        self._conn.execute(
            "UPDATE conversation_notes SET is_active = 0 WHERE id = ?",
            (note_id,),
        )
        self._conn.commit()

    def auto_resolve_old_notes(
        self, user_id: int, persona: str, ttl_days: int = 14,
    ) -> int:
        """Resolve notes older than ttl_days. Returns count resolved."""
        cur = self._conn.execute(
            "UPDATE conversation_notes SET is_active = 0 "
            "WHERE user_id = ? AND persona = ? AND is_active = 1 "
            "AND created_at < datetime('now', ?)",
            (user_id, persona, f"-{ttl_days} days"),
        )
        self._conn.commit()
        return cur.rowcount

    # ── User facts ─────────────────────────────────────────────────────

    def get_active_facts(self, user_id: int) -> list[dict[str, Any]]:
        """Return non-deleted facts for a user."""
        rows = self._conn.execute(
            "SELECT * FROM user_facts "
            "WHERE user_id = ? AND is_deleted = 0 "
            "ORDER BY category, created_at",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_fact(
        self,
        user_id: int,
        fact: str,
        category: str = "personal",
        source: str = "extracted",
        persona: str | None = None,
    ) -> int:
        """Add a user fact. Returns its id."""
        cur = self._conn.execute(
            "INSERT INTO user_facts (user_id, fact, category, source, persona) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, fact, category, source, persona),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def deactivate_fact(self, fact_id: int) -> None:
        """Soft-delete a fact."""
        self._conn.execute(
            "UPDATE user_facts SET is_deleted = 1, updated_at = datetime('now') "
            "WHERE id = ?",
            (fact_id,),
        )
        self._conn.commit()

    # ── FTS5 search ────────────────────────────────────────────────────

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize a query string for FTS5.

        Removes special characters that FTS5 interprets as syntax
        (AND, OR, NOT, parentheses, quotes, colons, commas, etc.)
        and joins remaining words with spaces (implicit AND).
        """
        import re
        # Remove all non-word, non-whitespace characters (keeps letters, digits, _)
        # Also keep unicode letters (cyrillic, etc.)
        cleaned = re.sub(r"[^\w\s]", " ", query, flags=re.UNICODE)
        # Collapse whitespace and strip
        words = cleaned.split()
        # Filter out FTS5 keywords
        fts_keywords = {"and", "or", "not", "near"}
        words = [w for w in words if w.lower() not in fts_keywords]
        return " ".join(words)

    def fts_search(
        self, query: str, user_id: int, limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Full-text search across messages for a user.

        Returns messages with id, role, content, created_at, and FTS rank.
        """
        if not self._fts_available or not query.strip():
            return []
        sanitized = self._sanitize_fts_query(query)
        if not sanitized:
            return []
        try:
            rows = self._conn.execute(
                "SELECT m.id, m.role, m.content, m.created_at, "
                "       rank AS fts_rank "
                "FROM messages_fts f "
                "JOIN messages m ON m.id = f.rowid "
                "WHERE messages_fts MATCH ? AND m.user_id = ? "
                "ORDER BY rank "
                "LIMIT ?",
                (sanitized, user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as e:
            logger.warning("FTS search error: %s", e)
            return []
