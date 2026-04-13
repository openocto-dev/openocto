"""Web admin routes for external MCP server management.

Handles HTML form actions that back the /mcp admin page.

These are **form-action** routes (return 302 redirects with flash messages),
deliberately separate from the JSON API at /api/v1/mcp/servers/*.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flash_redirect(location: str, message: str, flash_type: str = "info") -> web.Response:
    sep = "&" if "?" in location else "?"
    url = f"{location}{sep}flash={quote(message)}&flash_type={flash_type}"
    raise web.HTTPFound(url)


def _get_store_and_registry(octo):
    """Return (store, secrets, registry) tuple or (None, None, None)."""
    store = getattr(octo, "_mcp_store", None)
    secrets = getattr(octo, "_mcp_secrets", None)
    registry = getattr(octo, "_mcp_client_registry", None)
    return store, secrets, registry


def _parse_headers(raw: str) -> dict[str, str]:
    """Parse 'Key: Value\\n...' textarea into a dict."""
    headers = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            headers[key.strip()] = val.strip()
    return headers


def _parse_allowlist(raw: str) -> list[str]:
    """Parse one-tool-per-line textarea into a list."""
    tools = []
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tools.append(line)
    return tools


def _parse_args(raw: str) -> list[str]:
    """Parse one-arg-per-line textarea into a list (for stdio transports)."""
    args = []
    for line in raw.splitlines():
        line = line.rstrip()  # preserve leading whitespace in case user wants it
        if line.strip() and not line.strip().startswith("#"):
            args.append(line.strip())
    return args


def _parse_env(raw: str) -> dict[str, str]:
    """Parse 'KEY=VALUE' textarea into a dict (for stdio transports)."""
    env: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def _mask_env(env: dict[str, str]) -> str:
    """Return env as textarea text with values masked."""
    lines = []
    for k, v in env.items():
        if len(v) > 8:
            masked = v[:4] + "****"
        else:
            masked = "****"
        lines.append(f"{k}={masked}")
    return "\n".join(lines)


def _mask_headers(headers: dict[str, str]) -> str:
    """Return headers as textarea text with secrets masked."""
    lines = []
    for k, v in headers.items():
        if k.lower() == "authorization" and len(v) > 15:
            parts = v.split(" ", 1)
            masked = f"{parts[0]} ****" if len(parts) > 1 else "****"
            lines.append(f"{k}: {masked}")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    return dict(row) if hasattr(row, "keys") else row


# ── Pages ─────────────────────────────────────────────────────────────────────

@routes.get("/mcp")
@aiohttp_jinja2.template("mcp_clients.html")
async def mcp_list_page(request: web.Request) -> dict:
    octo = request.app["octo"]
    store, secrets, registry = _get_store_and_registry(octo)
    skills = getattr(octo, "_skills", None)
    flash = request.query.get("flash", "")
    flash_type = request.query.get("flash_type", "info")

    builtin = {
        "tool_count": len(skills) if skills else 0,
        "tools": skills.names() if skills else [],
    }

    servers = []
    if store is not None:
        for row in store.list():
            s = _row_to_dict(row)
            if registry:
                status = registry.get_status(s["id"])
                s["tool_count"] = status.get("tool_count", 0)
                s["tools"] = registry.list_tool_names(s["id"])
                s["unhealthy"] = status.get("unhealthy", False)
            else:
                s["tool_count"] = 0
                s["tools"] = []
                s["unhealthy"] = False
            servers.append(s)

    return {
        "page": "mcp",
        "version": __version__,
        "builtin": builtin,
        "servers": servers,
        "flash": flash,
        "flash_type": flash_type,
    }


@routes.get("/mcp/new")
@aiohttp_jinja2.template("mcp_client_edit.html")
async def mcp_new_form(request: web.Request) -> dict:
    return {
        "page": "mcp",
        "version": __version__,
        "server": None,
        "headers_raw": "",
        "allowlist_raw": "",
        "args_raw": "",
        "env_raw": "",
        "flash": request.query.get("flash", ""),
        "flash_type": request.query.get("flash_type", "info"),
    }


@routes.get("/mcp/{server_id}/edit")
@aiohttp_jinja2.template("mcp_client_edit.html")
async def mcp_edit_form(request: web.Request) -> dict:
    octo = request.app["octo"]
    store, secrets, registry = _get_store_and_registry(octo)
    if store is None:
        raise web.HTTPFound("/mcp")

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        raise web.HTTPFound("/mcp")

    row = store.get(server_id)
    if row is None:
        raise web.HTTPFound("/mcp")

    s = _row_to_dict(row)
    existing_headers = secrets.get_headers(s["name"]) if secrets else {}
    headers_raw = _mask_headers(existing_headers)
    allowlist_raw = "\n".join(s.get("tool_allowlist") or [])
    args_raw = "\n".join(s.get("args") or [])
    existing_env = secrets.get_env(s["name"]) if secrets else {}
    env_raw = _mask_env(existing_env)

    return {
        "page": "mcp",
        "version": __version__,
        "server": s,
        "headers_raw": headers_raw,
        "allowlist_raw": allowlist_raw,
        "args_raw": args_raw,
        "env_raw": env_raw,
        "flash": request.query.get("flash", ""),
        "flash_type": request.query.get("flash_type", "info"),
    }


# ── Form actions ──────────────────────────────────────────────────────────────

@routes.post("/api/mcp/servers")
async def mcp_create(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    store, secrets, registry = _get_store_and_registry(octo)
    if store is None:
        _flash_redirect("/mcp", "MCP client not configured", "error")

    data = await request.post()
    name = data.get("name", "").strip()
    url = data.get("url", "").strip()
    headers_raw = data.get("headers_raw", "")
    allowlist_raw = data.get("allowlist_raw", "")
    enabled = bool(data.get("enabled"))
    transport = data.get("transport", "http")
    command = data.get("command", "").strip() or None
    args_raw = data.get("args_raw", "")
    env_raw = data.get("env_raw", "")

    if not name:
        _flash_redirect("/mcp/new", "Name is required", "error")
    if transport == "stdio":
        if not command:
            _flash_redirect("/mcp/new", "Command is required for stdio transport", "error")
    else:
        if not url:
            _flash_redirect("/mcp/new", "URL is required for HTTP transport", "error")

    headers = _parse_headers(headers_raw) if transport != "stdio" else {}
    args_list = _parse_args(args_raw) if transport == "stdio" else []
    env = _parse_env(env_raw) if transport == "stdio" else {}
    tool_allowlist = _parse_allowlist(allowlist_raw)

    try:
        server_id = store.create(
            name, url if transport != "stdio" else "",
            transport=transport,
            command=command,
            args=args_list,
            tool_allowlist=tool_allowlist,
            enabled=enabled,
        )
    except ValueError as exc:
        _flash_redirect("/mcp/new", str(exc), "error")

    if headers:
        secrets.set_headers(name, headers)
    if env:
        secrets.set_env(name, env)

    if registry and enabled:
        try:
            row = store.get(server_id)
            import asyncio
            asyncio.create_task(registry.add_server(row))
        except Exception as exc:
            logger.warning("MCP registry.add_server failed: %s", exc)

    _flash_redirect("/mcp", f"Server '{name}' added", "success")


@routes.post("/api/mcp/servers/{server_id}/edit")
async def mcp_update(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    store, secrets, registry = _get_store_and_registry(octo)
    if store is None:
        _flash_redirect("/mcp", "MCP client not configured", "error")

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        _flash_redirect("/mcp", "Invalid server ID", "error")

    row = store.get(server_id)
    if row is None:
        _flash_redirect("/mcp", "Server not found", "error")

    data = await request.post()
    url = data.get("url", "").strip()
    headers_raw = data.get("headers_raw", "")
    allowlist_raw = data.get("allowlist_raw", "")
    enabled = bool(data.get("enabled"))
    transport = data.get("transport", "http")
    command = data.get("command", "").strip() or None
    args_raw = data.get("args_raw", "")
    env_raw = data.get("env_raw", "")

    update_fields: dict = {"enabled": enabled, "transport": transport}
    needs_refresh = False

    if transport == "stdio":
        if command is not None:
            update_fields["command"] = command
            needs_refresh = True
        update_fields["args"] = _parse_args(args_raw)
        needs_refresh = True
        update_fields["url"] = ""
    else:
        if url:
            update_fields["url"] = url
            needs_refresh = True

    update_fields["tool_allowlist"] = _parse_allowlist(allowlist_raw)

    store.update(server_id, **update_fields)

    if transport == "stdio":
        env = _parse_env(env_raw)
        if env:
            secrets.set_env(row["name"], env)
            needs_refresh = True
    else:
        headers = _parse_headers(headers_raw)
        if headers:
            secrets.set_headers(row["name"], headers)
            needs_refresh = True

    if registry and needs_refresh:
        try:
            import asyncio
            asyncio.create_task(registry.refresh_one(server_id))
        except Exception as exc:
            logger.warning("MCP registry.refresh_one failed: %s", exc)

    _flash_redirect("/mcp", f"Server '{row['name']}' updated", "success")


@routes.post("/api/mcp/servers/{server_id}/delete")
async def mcp_delete(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    store, secrets, registry = _get_store_and_registry(octo)
    if store is None:
        _flash_redirect("/mcp", "MCP client not configured", "error")

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        _flash_redirect("/mcp", "Invalid server ID", "error")

    row = store.get(server_id)
    if row is None:
        _flash_redirect("/mcp", "Server not found", "error")

    name = row["name"]
    if registry:
        try:
            import asyncio
            asyncio.create_task(registry.remove_server(server_id))
        except Exception as exc:
            logger.warning("MCP registry.remove_server failed: %s", exc)

    secrets.delete(name)
    store.delete(server_id)
    _flash_redirect("/mcp", f"Server '{name}' deleted", "success")


@routes.post("/api/mcp/servers/{server_id}/toggle")
async def mcp_toggle(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    store, secrets, registry = _get_store_and_registry(octo)
    if store is None:
        _flash_redirect("/mcp", "MCP client not configured", "error")

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        _flash_redirect("/mcp", "Invalid server ID", "error")

    row = store.get(server_id)
    if row is None:
        _flash_redirect("/mcp", "Server not found", "error")

    new_enabled = not bool(row["enabled"])
    store.update(server_id, enabled=new_enabled)

    if registry:
        try:
            import asyncio
            if new_enabled:
                asyncio.create_task(registry.refresh_one(server_id))
            else:
                asyncio.create_task(registry.remove_server(server_id))
        except Exception as exc:
            logger.warning("MCP toggle failed: %s", exc)

    state = "enabled" if new_enabled else "disabled"
    _flash_redirect("/mcp", f"Server '{row['name']}' {state}", "success")


@routes.post("/api/mcp/servers/{server_id}/test")
async def mcp_test(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    store, secrets, registry = _get_store_and_registry(octo)
    if store is None:
        _flash_redirect("/mcp", "MCP client not configured", "error")

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        _flash_redirect("/mcp", "Invalid server ID", "error")

    row = store.get(server_id)
    if row is None:
        _flash_redirect("/mcp", "Server not found", "error")

    from openocto.mcp_client import MCPClient, MCPStdioClient, MCPClientError
    transport = (row.get("transport") or "http").lower()
    if transport == "stdio":
        env = secrets.get_env(row["name"]) if secrets else {}
        client = MCPStdioClient(
            row["name"],
            row.get("command") or "",
            args=row.get("args") or [],
            env=env or None,
            timeout=15.0,
        )
    else:
        headers = secrets.get_headers(row["name"]) if secrets else {}
        client = MCPClient(
            row["name"], row.get("url") or "", headers=headers or None, timeout=15.0,
        )
    try:
        try:
            await client.connect()
            tools = await client.list_tools()
        except MCPClientError as exc:
            _flash_redirect("/mcp", f"Connection failed: {exc}", "error")
        except web.HTTPException:
            raise
        except Exception as exc:
            logger.exception("mcp_test: unexpected error for %r", row["name"])
            _flash_redirect("/mcp", f"Connection failed: {type(exc).__name__}: {exc}", "error")
        n = len(tools)
        _flash_redirect("/mcp", f"Connected to '{row['name']}' — {n} tool{'s' if n != 1 else ''} available", "success")
    finally:
        try:
            await client.close()
        except Exception:
            pass


@routes.post("/api/mcp/servers/{server_id}/refresh")
async def mcp_refresh(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    store, secrets, registry = _get_store_and_registry(octo)
    if store is None:
        _flash_redirect("/mcp", "MCP client not configured", "error")

    try:
        server_id = int(request.match_info["server_id"])
    except ValueError:
        _flash_redirect("/mcp", "Invalid server ID", "error")

    row = store.get(server_id)
    if row is None:
        _flash_redirect("/mcp", "Server not found", "error")

    if registry:
        try:
            await registry.refresh_one(server_id)
            row = store.get(server_id)
            status = row.get("last_status", "?")
            ft = "success" if status == "connected" else "error"
            _flash_redirect("/mcp", f"Server '{row['name']}' refreshed — status: {status}", ft)
        except Exception as exc:
            _flash_redirect("/mcp", f"Refresh failed: {exc}", "error")

    _flash_redirect("/mcp", "No registry running", "error")
