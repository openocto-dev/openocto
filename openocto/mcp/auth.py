"""MCP Bearer-token authentication.

The token is stored in ~/.openocto/mcp-token (chmod 600, created on first
use).  Every request must include `Authorization: Bearer <token>` unless
`require_auth` is False in MCPConfig.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

_TOKEN_PATH = Path.home() / ".openocto" / "mcp-token"


def get_or_create_token() -> str:
    """Return existing token or generate a new one and persist it."""
    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _TOKEN_PATH.exists():
        return _TOKEN_PATH.read_text().strip()
    token = secrets.token_hex(32)
    _TOKEN_PATH.write_text(token)
    # chmod 600 — owner read/write only
    _TOKEN_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return token


def verify_token(provided: str | None, expected: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    if not provided:
        return False
    return secrets.compare_digest(provided, expected)


def extract_bearer(authorization_header: str | None) -> str | None:
    """Parse 'Bearer <token>' from an Authorization header value."""
    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None
