"""SQLite DAO for external MCP server metadata.

Secrets (bearer tokens, headers) are NOT stored here — they live in
``~/.openocto/mcp-secrets.yaml`` (chmod 600) via :class:`MCPSecretsStore`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

_NAME_REGEX_PATTERN = r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    # Decode JSON-encoded fields
    raw = d.get("tool_allowlist_json") or "[]"
    try:
        d["tool_allowlist"] = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        d["tool_allowlist"] = []
    args_raw = d.get("args_json") or "[]"
    try:
        d["args"] = json.loads(args_raw)
    except (json.JSONDecodeError, TypeError):
        d["args"] = []
    return d


class MCPServerStore:
    """DAO for the ``mcp_servers`` SQLite table.

    Shares the connection from :class:`~openocto.history.HistoryStore` so
    writes participate in the same WAL journal and don't need a separate lock.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Read ──────────────────────────────────────────────────────────────

    def list(self) -> list[dict[str, Any]]:
        """Return all servers ordered by name."""
        rows = self._conn.execute(
            "SELECT * FROM mcp_servers ORDER BY name"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def list_enabled(self) -> list[dict[str, Any]]:
        """Return only enabled servers."""
        rows = self._conn.execute(
            "SELECT * FROM mcp_servers WHERE enabled = 1 ORDER BY name"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get(self, server_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM mcp_servers WHERE id = ?", (server_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None

    def get_by_name(self, name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM mcp_servers WHERE name = ?", (name,)
        ).fetchone()
        return _row_to_dict(row) if row else None

    # ── Write ─────────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        url: str,
        *,
        transport: str = "http",
        command: str | None = None,
        args: list[str] | None = None,
        tool_allowlist: list[str] | None = None,
        enabled: bool = True,
    ) -> int:
        """Insert a new server record.  Returns the new ``id``.

        Raises :class:`ValueError` if ``name`` is not unique.
        """
        allowlist_json = json.dumps(tool_allowlist or [])
        args_json = json.dumps(args or [])
        try:
            cur = self._conn.execute(
                """
                INSERT INTO mcp_servers
                    (name, url, transport, command, args_json, tool_allowlist_json, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, url, transport, command, args_json, allowlist_json, int(enabled)),
            )
            self._conn.commit()
            logger.debug("MCPServerStore: created server %r (id=%d)", name, cur.lastrowid)
            return cur.lastrowid  # type: ignore[return-value]
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"MCP server name {name!r} already exists") from exc

    def update(self, server_id: int, **fields: Any) -> bool:
        """Partial update — only supplied keyword args are changed.

        Supported keys: ``name``, ``url``, ``transport``, ``command``,
        ``args`` (list), ``tool_allowlist`` (list), ``enabled`` (bool/int),
        ``last_status``, ``last_error``, ``last_checked_at``.

        Returns ``True`` if a row was updated.
        """
        if not fields:
            return False

        # Normalise list-typed fields → JSON columns
        if "tool_allowlist" in fields:
            fields["tool_allowlist_json"] = json.dumps(fields.pop("tool_allowlist"))
        if "args" in fields:
            fields["args_json"] = json.dumps(fields.pop("args") or [])
        if "enabled" in fields:
            fields["enabled"] = int(bool(fields["enabled"]))

        # Always bump updated_at
        fields["updated_at"] = "datetime('now')"
        _raw_updated_at = fields.pop("updated_at")

        set_clauses = ", ".join(f"{k} = ?" for k in fields)
        set_clauses += ", updated_at = datetime('now')"
        values = list(fields.values()) + [server_id]

        cur = self._conn.execute(
            f"UPDATE mcp_servers SET {set_clauses} WHERE id = ?",
            values,
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete(self, server_id: int) -> bool:
        """Delete a server by id. Returns ``True`` if a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM mcp_servers WHERE id = ?", (server_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def set_status(
        self,
        server_id: int,
        status: str,
        error: str | None = None,
    ) -> None:
        """Update connection status fields (called by the registry)."""
        self._conn.execute(
            """
            UPDATE mcp_servers
            SET last_status = ?, last_error = ?, last_checked_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (status, error, server_id),
        )
        self._conn.commit()
