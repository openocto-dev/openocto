"""JSON API v1 — pure JSON endpoints for mobile / external clients.

Design notes
------------
This namespace is **deliberately separate** from the form-action
handlers under ``/api/*`` (which return 302 redirects with flash
messages and exist to back HTML forms).  Mobile apps and CLI clients
need:

  * Bearer-token auth (no cookies / sessions)
  * Versioned URLs (``/api/v1/...``) so we can evolve without breaking
    deployed mobile clients
  * Structured JSON errors (``{"error": "...", "message": "..."}``)
  * Idempotent CRUD shapes — no redirects, no flash strings

The two surfaces share the underlying business logic (HistoryStore,
PersonaManager, AIRouter, SkillRegistry) — only the HTTP layer is
duplicated.  That's the intentional split.

Auth: ``Authorization: Bearer <token>`` from ``~/.openocto/api-token``.
Get the token via ``openocto api token``.
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from openocto import __version__
from openocto.web.api_auth import require_api_token

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _bad_request(message: str) -> web.Response:
    return web.json_response({"error": "bad_request", "message": message}, status=400)


def _not_found(message: str) -> web.Response:
    return web.json_response({"error": "not_found", "message": message}, status=404)


def _service_unavailable(message: str) -> web.Response:
    return web.json_response(
        {"error": "service_unavailable", "message": message}, status=503,
    )


async def _read_json(request: web.Request) -> dict:
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data
    except Exception as e:
        raise web.HTTPBadRequest(
            text=f'{{"error":"bad_request","message":"Invalid JSON: {e}"}}',
            content_type="application/json",
        )


def _resolve_user_id(octo, payload: dict | None = None) -> int | None:
    if payload and payload.get("user_id"):
        try:
            return int(payload["user_id"])
        except (TypeError, ValueError):
            return None
    return octo._current_user_id


def _resolve_persona(octo, payload: dict | None = None) -> str:
    if payload and payload.get("persona"):
        return str(payload["persona"])
    return octo._persona.name if octo._persona else "octo"


# ── Status / health ──────────────────────────────────────────────────────────


@routes.get("/api/v1/status")
@require_api_token
async def status(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    skills = getattr(octo, "_skills", None)
    return web.json_response({
        "version": __version__,
        "active_user_id": octo._current_user_id,
        "active_persona": octo._persona.name if octo._persona else None,
        "ai_backend": (
            octo._ai_router.active_backend_name
            if getattr(octo, "_ai_router", None) else None
        ),
        "skills": skills.names() if skills else [],
        "history_available": getattr(octo, "_history_store", None) is not None,
    })


# ── Users ────────────────────────────────────────────────────────────────────


@routes.get("/api/v1/users")
@require_api_token
async def list_users(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")
    return web.json_response({
        "users": hs.list_users(),
        "active_user_id": octo._current_user_id,
    })


@routes.post("/api/v1/users")
@require_api_token
async def create_user(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    data = await _read_json(request)
    name = (data.get("name") or "").strip()
    if not name:
        return _bad_request("name is required")
    if hs.get_user_by_name(name):
        return _bad_request(f"User {name!r} already exists")

    user_id = hs.create_user(name, is_default=bool(data.get("is_default", False)))
    return web.json_response({"id": user_id, "name": name}, status=201)


@routes.post("/api/v1/users/{user_id}/activate")
@require_api_token
async def activate_user(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    try:
        user_id = int(request.match_info["user_id"])
    except ValueError:
        return _bad_request("Invalid user_id")

    user = next((u for u in hs.list_users() if u["id"] == user_id), None)
    if not user:
        return _not_found(f"User {user_id} not found")

    octo._current_user_id = user_id
    return web.json_response({"active_user_id": user_id, "name": user["name"]})


@routes.post("/api/v1/users/{user_id}/default")
@require_api_token
async def set_default_user(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    try:
        user_id = int(request.match_info["user_id"])
    except ValueError:
        return _bad_request("Invalid user_id")

    hs.set_default_user(user_id)
    return web.json_response({"default_user_id": user_id})


@routes.delete("/api/v1/users/{user_id}")
@require_api_token
async def delete_user(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    try:
        user_id = int(request.match_info["user_id"])
    except ValueError:
        return _bad_request("Invalid user_id")

    if user_id == octo._current_user_id:
        return _bad_request("Cannot delete the active user")

    hs.delete_user(user_id)
    return web.json_response({"deleted": True, "id": user_id})


# ── Personas ─────────────────────────────────────────────────────────────────


@routes.get("/api/v1/personas")
@require_api_token
async def list_personas(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    pm = getattr(octo, "_persona_manager", None)
    if not pm:
        return _service_unavailable("Persona manager not available")
    return web.json_response({
        "personas": pm.list_personas(),
        "active_persona": octo._persona.name if octo._persona else None,
    })


@routes.post("/api/v1/personas/{name}/activate")
@require_api_token
async def activate_persona(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    pm = getattr(octo, "_persona_manager", None)
    if not pm:
        return _service_unavailable("Persona manager not available")

    name = request.match_info["name"]
    try:
        octo._persona = pm.activate(name)
    except (ValueError, KeyError):
        return _not_found(f"Persona {name!r} not found")

    return web.json_response({"active_persona": name})


# ── Messages ─────────────────────────────────────────────────────────────────


@routes.get("/api/v1/messages")
@require_api_token
async def list_messages(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    user_id = _resolve_user_id(octo, dict(request.query))
    persona = _resolve_persona(octo, dict(request.query))
    if not user_id:
        return _bad_request("No active user_id")

    try:
        limit = int(request.query.get("limit", "50"))
    except ValueError:
        return _bad_request("Invalid limit")

    after_id = request.query.get("after_id")
    if after_id is not None:
        try:
            after = int(after_id)
        except ValueError:
            return _bad_request("Invalid after_id")
        messages = hs.get_messages_after(user_id, persona, after, limit=limit)
    else:
        messages = hs.get_recent_messages(user_id, persona, limit=limit)

    return web.json_response({
        "user_id": user_id,
        "persona": persona,
        "messages": messages,
    })


@routes.post("/api/v1/messages")
@require_api_token
async def send_message(request: web.Request) -> web.Response:
    """Mirror of /api/messages/send but pure JSON input/output, no TTS by default."""
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")
    if not octo._ai_router:
        return _service_unavailable("AI router not available")

    data = await _read_json(request)
    content = (data.get("content") or "").strip()
    if not content:
        return _bad_request("content is required")

    user_id = _resolve_user_id(octo, data)
    persona = _resolve_persona(octo, data)
    if not user_id:
        return _bad_request("No active user_id")

    user_msg_id = hs.add_message(user_id, persona, "user", content)

    history = hs.get_recent_messages(user_id, persona, limit=20)
    ai_history = [{"role": m["role"], "content": m["content"]} for m in history]
    if ai_history and ai_history[-1]["role"] == "user":
        ai_history.pop()

    system_prompt = octo._persona.system_prompt if octo._persona else ""

    skills = getattr(octo, "_skills", None)
    if skills is not None:
        skills.bind_context(
            history=hs,
            user_id=user_id,
            persona=persona,
            player=getattr(octo, "_player", None),
            loop=asyncio.get_event_loop(),
        )

    try:
        reply = await octo._ai_router.send(
            user_text=content,
            history=ai_history,
            system_prompt=system_prompt,
            skills=skills,
        )
    except Exception as e:
        logger.exception("AI router failed")
        return web.json_response(
            {"error": "ai_failed", "message": str(e)}, status=502,
        )

    assistant_msg_id = hs.add_message(user_id, persona, "assistant", reply)

    return web.json_response({
        "user_msg_id": user_msg_id,
        "assistant_msg_id": assistant_msg_id,
        "role": "assistant",
        "content": reply,
    })


@routes.delete("/api/v1/messages")
@require_api_token
async def clear_messages(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    user_id = _resolve_user_id(octo, dict(request.query))
    persona = request.query.get("persona") or None
    if not user_id:
        return _bad_request("No active user_id")

    count = hs.clear_history(user_id, persona)
    return web.json_response({"deleted": count})


# ── Memory ───────────────────────────────────────────────────────────────────


@routes.get("/api/v1/memory/facts")
@require_api_token
async def list_facts(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    user_id = _resolve_user_id(octo, dict(request.query))
    if not user_id:
        return _bad_request("No active user_id")

    return web.json_response({"facts": hs.get_active_facts(user_id)})


@routes.post("/api/v1/memory/facts")
@require_api_token
async def add_fact(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    data = await _read_json(request)
    user_id = _resolve_user_id(octo, data)
    if not user_id:
        return _bad_request("No active user_id")

    text = (data.get("text") or "").strip()
    category = (data.get("category") or "general").strip() or "general"
    if not text:
        return _bad_request("text is required")

    fact_id = hs.add_fact(user_id, category, text)
    return web.json_response({"id": fact_id, "text": text, "category": category}, status=201)


@routes.delete("/api/v1/memory/facts/{fact_id}")
@require_api_token
async def delete_fact(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    try:
        fact_id = int(request.match_info["fact_id"])
    except ValueError:
        return _bad_request("Invalid fact_id")

    hs.deactivate_fact(fact_id)
    return web.json_response({"deleted": True, "id": fact_id})


@routes.get("/api/v1/memory/notes")
@require_api_token
async def list_notes(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    user_id = _resolve_user_id(octo, dict(request.query))
    if not user_id:
        return _bad_request("No active user_id")

    return web.json_response({"notes": hs.get_active_notes(user_id)})


@routes.post("/api/v1/memory/notes/{note_id}/resolve")
@require_api_token
async def resolve_note(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return _service_unavailable("History store not available")

    try:
        note_id = int(request.match_info["note_id"])
    except ValueError:
        return _bad_request("Invalid note_id")

    hs.resolve_note(note_id)
    return web.json_response({"resolved": True, "id": note_id})


# ── MCP Clients ───────────────────────────────────────────────────────────────

import re as _re
_MCP_NAME_RE = _re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


def _mcp_get_registry(octo):
    """Return (store, secrets, registry) or None if unavailable."""
    store = getattr(octo, "_mcp_store", None)
    secrets = getattr(octo, "_mcp_secrets", None)
    registry = getattr(octo, "_mcp_client_registry", None)
    if store is None or secrets is None:
        return None
    return store, secrets, registry


def _mcp_row_to_response(row: dict, registry=None) -> dict:
    """Build a response-safe dict from a DB row + live registry status."""
    resp = {
        "id": row["id"],
        "name": row["name"],
        "url": row["url"],
        "transport": row["transport"],
        "tool_allowlist": row.get("tool_allowlist") or [],
        "enabled": bool(row["enabled"]),
        "last_status": row.get("last_status"),
        "last_error": row.get("last_error"),
        "last_checked_at": row.get("last_checked_at"),
        "created_at": row.get("created_at"),
    }
    if registry is not None:
        status = registry.get_status(row["id"])
        resp["tool_count"] = status.get("tool_count", 0)
        resp["tools"] = registry.list_tool_names(row["id"])
        resp["unhealthy"] = status.get("unhealthy", False)
    return resp


@routes.get("/api/v1/mcp/servers")
@require_api_token
async def mcp_list_servers(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    result = _mcp_get_registry(octo)
    if result is None:
        return _service_unavailable("MCP client not available")
    store, secrets, registry = result
    skills = getattr(octo, "_skills", None)
    builtin = {
        "name": "openocto",
        "url": None,
        "builtin": True,
        "tool_count": len(skills) if skills else 0,
        "tools": skills.names() if skills else [],
    }
    servers = [_mcp_row_to_response(row, registry) for row in store.list()]
    return web.json_response({"builtin": builtin, "servers": servers})


@routes.post("/api/v1/mcp/servers")
@require_api_token
async def mcp_create_server(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    result = _mcp_get_registry(octo)
    if result is None:
        return _service_unavailable("MCP client not available")
    store, secrets, registry = result

    data = await _read_json(request)
    name = data.get("name", "").strip()
    url = data.get("url", "").strip()

    if not _MCP_NAME_RE.match(name):
        return _bad_request("name must match ^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    if not url.startswith(("http://", "https://")):
        return _bad_request("url must start with http:// or https://")

    headers = data.get("headers") or {}
    tool_allowlist = data.get("tool_allowlist") or []
    transport = data.get("transport", "http")
    enabled = bool(data.get("enabled", True))

    try:
        server_id = store.create(
            name, url,
            transport=transport,
            tool_allowlist=tool_allowlist,
            enabled=enabled,
        )
    except ValueError as exc:
        return _bad_request(str(exc))

    if headers:
        secrets.set_headers(name, headers)

    row = store.get(server_id)
    if registry and enabled:
        try:
            await registry.add_server(row)
        except Exception as exc:
            logger.warning("MCP registry.add_server failed: %s", exc)

    return web.json_response(_mcp_row_to_response(row, registry), status=201)


@routes.get("/api/v1/mcp/servers/{server_id}")
@require_api_token
async def mcp_get_server(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    result = _mcp_get_registry(octo)
    if result is None:
        return _service_unavailable("MCP client not available")
    store, secrets, registry = result

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        return _bad_request("Invalid server_id")

    row = store.get(server_id)
    if row is None:
        return _not_found(f"Server {server_id} not found")
    return web.json_response(_mcp_row_to_response(row, registry))


@routes.patch("/api/v1/mcp/servers/{server_id}")
@require_api_token
async def mcp_update_server(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    result = _mcp_get_registry(octo)
    if result is None:
        return _service_unavailable("MCP client not available")
    store, secrets, registry = result

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        return _bad_request("Invalid server_id")

    row = store.get(server_id)
    if row is None:
        return _not_found(f"Server {server_id} not found")

    data = await _read_json(request)
    needs_refresh = False

    update_fields = {}
    if "url" in data:
        url = data["url"].strip()
        if not url.startswith(("http://", "https://")):
            return _bad_request("url must start with http:// or https://")
        update_fields["url"] = url
        needs_refresh = True
    if "enabled" in data:
        update_fields["enabled"] = bool(data["enabled"])
    if "tool_allowlist" in data:
        update_fields["tool_allowlist"] = data["tool_allowlist"] or []
        needs_refresh = True
    if "transport" in data:
        update_fields["transport"] = data["transport"]

    if update_fields:
        store.update(server_id, **update_fields)

    if "headers" in data:
        secrets.set_headers(row["name"], data["headers"] or {})
        needs_refresh = True

    if needs_refresh and registry:
        try:
            await registry.refresh_one(server_id)
        except Exception as exc:
            logger.warning("MCP registry.refresh_one failed: %s", exc)

    row = store.get(server_id)
    return web.json_response(_mcp_row_to_response(row, registry))


@routes.delete("/api/v1/mcp/servers/{server_id}")
@require_api_token
async def mcp_delete_server(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    result = _mcp_get_registry(octo)
    if result is None:
        return _service_unavailable("MCP client not available")
    store, secrets, registry = result

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        return _bad_request("Invalid server_id")

    row = store.get(server_id)
    if row is None:
        return _not_found(f"Server {server_id} not found")

    if registry:
        try:
            await registry.remove_server(server_id)
        except Exception as exc:
            logger.warning("MCP registry.remove_server failed: %s", exc)

    secrets.delete(row["name"])
    store.delete(server_id)
    return web.json_response({"deleted": True, "id": server_id})


@routes.post("/api/v1/mcp/servers/{server_id}/test")
@require_api_token
async def mcp_test_server(request: web.Request) -> web.Response:
    """Create an ephemeral client, connect, list tools, close.  No registry changes."""
    octo = request.app["octo"]
    result = _mcp_get_registry(octo)
    if result is None:
        return _service_unavailable("MCP client not available")
    store, secrets, registry = result

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        return _bad_request("Invalid server_id")

    row = store.get(server_id)
    if row is None:
        return _not_found(f"Server {server_id} not found")

    from openocto.mcp_client import MCPClient, MCPClientError
    headers = secrets.get_headers(row["name"])
    client = MCPClient(row["name"], row["url"], headers=headers or None, timeout=15.0)
    try:
        await client.connect()
        tools = await client.list_tools()
        tool_names = [t.get("name") for t in tools]
        return web.json_response({"connected": True, "tools": tool_names, "tool_count": len(tools)})
    except MCPClientError as exc:
        return web.json_response(
            {"connected": False, "error": str(exc)}, status=502
        )
    finally:
        await client.close()


@routes.post("/api/v1/mcp/servers/{server_id}/refresh")
@require_api_token
async def mcp_refresh_server(request: web.Request) -> web.Response:
    """Re-connect a server and refresh its tools in the registry."""
    octo = request.app["octo"]
    result = _mcp_get_registry(octo)
    if result is None:
        return _service_unavailable("MCP client not available")
    store, secrets, registry = result

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        return _bad_request("Invalid server_id")

    row = store.get(server_id)
    if row is None:
        return _not_found(f"Server {server_id} not found")

    if registry:
        try:
            await registry.refresh_one(server_id)
        except Exception as exc:
            logger.warning("MCP refresh failed: %s", exc)

    row = store.get(server_id)
    return web.json_response(_mcp_row_to_response(row, registry))
