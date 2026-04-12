"""Bearer-token auth for the JSON API (`/api/v1/*`).

The token is stored in ~/.openocto/api-token (chmod 600, generated on
first use).  Every JSON API request must include
``Authorization: Bearer <token>``.

Kept separate from the MCP token (~/.openocto/mcp-token) so the two can
be revoked independently — e.g. you can rotate the mobile app token
without disturbing your editor's MCP integration.
"""

from __future__ import annotations

import secrets
import stat
from pathlib import Path

from aiohttp import web

_TOKEN_PATH = Path.home() / ".openocto" / "api-token"


def get_or_create_api_token() -> str:
    """Return the existing API token, or generate one and persist it."""
    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _TOKEN_PATH.exists():
        return _TOKEN_PATH.read_text().strip()
    token = secrets.token_hex(32)
    _TOKEN_PATH.write_text(token)
    _TOKEN_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return token


def revoke_api_token() -> None:
    """Delete the persisted token (next call will regenerate)."""
    if _TOKEN_PATH.exists():
        _TOKEN_PATH.unlink()


def _extract_bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def require_api_token(handler):
    """Decorator: reject requests without a valid Bearer token.

    Returns a JSON 401 instead of an HTML error page so mobile/CLI
    clients get a structured error.
    """
    async def wrapper(request: web.Request) -> web.Response:
        provided = _extract_bearer(request.headers.get("Authorization"))
        expected = get_or_create_api_token()
        if not provided or not secrets.compare_digest(provided, expected):
            return web.json_response(
                {"error": "unauthorized", "message": "Missing or invalid Bearer token"},
                status=401,
            )
        return await handler(request)
    return wrapper
