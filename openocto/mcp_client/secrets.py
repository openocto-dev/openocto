"""yaml-based secrets store for external MCP server headers/tokens.

Headers (e.g. ``Authorization: Bearer ntn_xxx``) must NOT live in SQLite —
they could end up in backups or version control.  Instead they go in a
separate file:

    ~/.openocto/mcp-secrets.yaml   (chmod 600)

Format::

    servers:
      notion:
        headers:
          Authorization: "Bearer ntn_xxx"
      github:
        headers:
          Authorization: "Bearer ghp_xxx"

Writes are **atomic** (write to temp → ``os.replace``) so a crash mid-write
cannot corrupt the file.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from openocto.config import USER_CONFIG_DIR

logger = logging.getLogger(__name__)

_DEFAULT_SECRETS_PATH = USER_CONFIG_DIR / "mcp-secrets.yaml"

_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


class MCPSecretsStore:
    """Read/write bearer tokens and custom headers per MCP server name.

    The file is created on first write with ``chmod 600``.  Subsequent reads
    never fail — a missing file returns empty headers.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_SECRETS_PATH

    # ── Internal helpers ──────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"servers": {}}
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            if "servers" not in data or not isinstance(data["servers"], dict):
                data["servers"] = {}
            return data
        except Exception as exc:
            logger.warning("Could not read %s: %s", self._path, exc)
            return {"servers": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp → replace
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                yaml.safe_dump(data, fh, allow_unicode=True, default_flow_style=False)
        except Exception:
            os.unlink(tmp)
            raise
        os.replace(tmp, self._path)
        # chmod 600 — always enforce, even if the file already existed
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass  # FAT / Windows — ignore

    def _validate_name(self, name: str) -> None:
        if not _NAME_RE.match(name):
            raise ValueError(
                f"Invalid MCP server name {name!r}. "
                "Must match ^[a-zA-Z][a-zA-Z0-9_-]{{0,63}}$"
            )

    # ── Public API ────────────────────────────────────────────────────────

    def get_headers(self, server_name: str) -> dict[str, str]:
        """Return the headers dict for *server_name* (empty dict if none)."""
        data = self._load()
        server = data["servers"].get(server_name, {})
        headers = server.get("headers", {})
        if not isinstance(headers, dict):
            return {}
        return {str(k): str(v) for k, v in headers.items()}

    def set_headers(self, server_name: str, headers: dict[str, str]) -> None:
        """Persist *headers* for *server_name*.  Existing headers are replaced."""
        self._validate_name(server_name)
        data = self._load()
        if server_name not in data["servers"]:
            data["servers"][server_name] = {}
        data["servers"][server_name]["headers"] = dict(headers)
        self._save(data)
        logger.debug("MCPSecretsStore: updated headers for %r", server_name)

    def get_env(self, server_name: str) -> dict[str, str]:
        """Return the env dict for *server_name* (used for stdio transports)."""
        data = self._load()
        server = data["servers"].get(server_name, {})
        env = server.get("env", {})
        if not isinstance(env, dict):
            return {}
        return {str(k): str(v) for k, v in env.items()}

    def set_env(self, server_name: str, env: dict[str, str]) -> None:
        """Persist *env* for *server_name*. Existing env is replaced."""
        self._validate_name(server_name)
        data = self._load()
        if server_name not in data["servers"]:
            data["servers"][server_name] = {}
        data["servers"][server_name]["env"] = dict(env)
        self._save(data)
        logger.debug("MCPSecretsStore: updated env for %r", server_name)

    def delete(self, server_name: str) -> None:
        """Remove the entry for *server_name* (no-op if missing)."""
        data = self._load()
        if server_name in data["servers"]:
            del data["servers"][server_name]
            self._save(data)
            logger.debug("MCPSecretsStore: removed secrets for %r", server_name)

    def list_names(self) -> list[str]:
        """Return names of servers that have stored secrets."""
        data = self._load()
        return list(data["servers"].keys())
