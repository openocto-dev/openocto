"""MCP (Model Context Protocol) server for OpenOcto skills.

Implements the Streamable HTTP transport (MCP 2024-11-05 spec):
  POST /mcp  — JSON-RPC 2.0 endpoint

Supported methods:
  initialize               — handshake, returns server capabilities
  notifications/initialized — client ack (no response needed)
  tools/list               — enumerate SkillRegistry tools
  tools/call               — invoke a skill and return result

Auth: Bearer token from ~/.openocto/mcp-token.
      Disable with MCPConfig(require_auth=False) for trusted LANs.

Usage:
    server = MCPServer(octo, config)
    await server.start()   # starts aiohttp on config.host:config.port
    ...
    await server.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import web

from openocto.mcp.auth import extract_bearer, get_or_create_token, verify_token

logger = logging.getLogger(__name__)

_MCP_VERSION = "2024-11-05"
_SERVER_NAME = "openocto"
_SERVER_VERSION_IMPORT = None  # resolved lazily


def _server_version() -> str:
    global _SERVER_VERSION_IMPORT
    if _SERVER_VERSION_IMPORT is None:
        try:
            from openocto import __version__
            _SERVER_VERSION_IMPORT = __version__
        except Exception:
            _SERVER_VERSION_IMPORT = "0.0.0"
    return _SERVER_VERSION_IMPORT


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────

def _ok(id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _err(id: Any, code: int, message: str, data: Any = None) -> dict:
    error: dict = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": error}


# JSON-RPC error codes
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


class MCPServer:
    """Embeddable MCP server — shares the app's asyncio event loop."""

    def __init__(self, octo: Any, config: Any) -> None:
        """
        octo   — the OpenOctoApp (or SimpleNamespace) that owns _skills
        config — MCPConfig instance
        """
        self._octo = octo
        self._config = config
        self._token: str | None = None
        self._runner: web.AppRunner | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._config.require_auth:
            self._token = get_or_create_token()
            logger.info("MCP token loaded from ~/.openocto/mcp-token")

        app = web.Application()
        app.router.add_post("/mcp", self._handle_rpc)
        # Convenience: GET /mcp returns server info (no auth needed)
        app.router.add_get("/mcp", self._handle_info)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._config.host, self._config.port)
        await site.start()
        logger.info(
            "MCP server listening on http://%s:%d/mcp",
            self._config.host, self._config.port,
        )

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # ── HTTP handlers ──────────────────────────────────────────────────────

    async def _handle_info(self, request: web.Request) -> web.Response:
        """GET /mcp — returns human-readable server info."""
        skills = self._octo._skills
        tool_names = skills.names() if skills else []
        body = {
            "name": _SERVER_NAME,
            "version": _server_version(),
            "protocol": _MCP_VERSION,
            "tools": tool_names,
            "auth_required": self._config.require_auth,
        }
        return web.json_response(body)

    async def _handle_rpc(self, request: web.Request) -> web.Response:
        # ── Auth check ──────────────────────────────────────────────────
        if self._config.require_auth:
            token = extract_bearer(request.headers.get("Authorization"))
            if not verify_token(token, self._token):
                return web.json_response(
                    _err(None, -32001, "Unauthorized"),
                    status=401,
                )

        # ── Parse body ──────────────────────────────────────────────────
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return web.json_response(_err(None, _PARSE_ERROR, "Parse error"))

        # Batch requests: list of RPC objects
        if isinstance(body, list):
            responses = [r for r in (await asyncio.gather(
                *[self._dispatch(item) for item in body]
            )) if r is not None]
            return web.json_response(responses)

        result = await self._dispatch(body)
        if result is None:
            # Notification — no response body
            return web.Response(status=204)
        return web.json_response(result)

    # ── RPC dispatcher ─────────────────────────────────────────────────────

    async def _dispatch(self, rpc: Any) -> dict | None:
        if not isinstance(rpc, dict):
            return _err(None, _INVALID_REQUEST, "Request must be an object")

        rpc_id = rpc.get("id")  # None for notifications
        method = rpc.get("method")
        params = rpc.get("params") or {}

        if not method:
            return _err(rpc_id, _INVALID_REQUEST, "Missing method")

        try:
            if method == "initialize":
                return await self._m_initialize(rpc_id, params)
            elif method == "notifications/initialized":
                # Client ack — notification, no response
                return None
            elif method == "tools/list":
                return await self._m_tools_list(rpc_id, params)
            elif method == "tools/call":
                return await self._m_tools_call(rpc_id, params)
            elif method == "ping":
                return _ok(rpc_id, {})
            else:
                return _err(rpc_id, _METHOD_NOT_FOUND, f"Method not found: {method}")
        except Exception as e:
            logger.exception("MCP dispatch error for method %s", method)
            return _err(rpc_id, _INTERNAL_ERROR, f"Internal error: {e}")

    # ── MCP method handlers ────────────────────────────────────────────────

    async def _m_initialize(self, rpc_id: Any, params: dict) -> dict:
        return _ok(rpc_id, {
            "protocolVersion": _MCP_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": _SERVER_NAME,
                "version": _server_version(),
            },
        })

    async def _m_tools_list(self, rpc_id: Any, params: dict) -> dict:
        skills = self._octo._skills
        tools = skills.mcp_tools() if skills else []
        return _ok(rpc_id, {"tools": tools})

    async def _m_tools_call(self, rpc_id: Any, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments") or {}

        if not name:
            return _err(rpc_id, _INVALID_PARAMS, "Missing tool name")

        skills = self._octo._skills
        if not skills:
            return _err(rpc_id, _INVALID_PARAMS, "No skills available")

        if skills.get(name) is None:
            return _err(rpc_id, _INVALID_PARAMS, f"Unknown tool: {name!r}")

        # Bind runtime context from app state so skills work correctly
        skills.bind_context(
            history=getattr(self._octo, "_history_store", None),
            user_id=getattr(self._octo, "_current_user_id", None),
            persona=_active_persona(self._octo),
            player=getattr(self._octo, "_player", None),
            loop=asyncio.get_event_loop(),
        )

        result_text = await skills.call(name, arguments)

        # MCP spec: content is a list of content blocks
        return _ok(rpc_id, {
            "content": [{"type": "text", "text": result_text}],
            "isError": result_text.startswith("Error:"),
        })


def _active_persona(octo: Any) -> str:
    """Return current persona name from app state."""
    persona = getattr(octo, "_persona", None)
    if persona and hasattr(persona, "name"):
        return persona.name
    return "octo"
