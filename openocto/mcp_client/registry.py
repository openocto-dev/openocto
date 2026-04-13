"""MCPClientRegistry — orchestrates all external MCP server connections.

Lifecycle::

    registry = MCPClientRegistry(store, secrets, skill_registry)
    await registry.start()          # connects all enabled servers
    # ... app runs ...
    await registry.stop()           # disconnects + unregisters all adapters

Hot-reload support:
* :meth:`add_server` — called after a new server is saved in the DB
* :meth:`remove_server` — removes from registry and unregisters its tools
* :meth:`refresh_one` — re-connect (e.g. after URL or header change)

Failure isolation: one server failing to connect does NOT prevent others
from being registered.  Errors are stored in the DB via
:meth:`MCPServerStore.set_status`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from openocto.mcp_client.adapter import MCPRemoteToolSkill
from openocto.mcp_client.client import MCPClient, MCPClientError, MCPStdioClient
from openocto.mcp_client.secrets import MCPSecretsStore
from openocto.mcp_client.store import MCPServerStore
from openocto.skills.base import SkillRegistry

logger = logging.getLogger(__name__)


class MCPClientRegistry:
    """Manages active MCP client connections and their tool registrations."""

    def __init__(
        self,
        store: MCPServerStore,
        secrets: MCPSecretsStore,
        skill_registry: SkillRegistry,
        *,
        connect_timeout: float = 10.0,
    ) -> None:
        self._store = store
        self._secrets = secrets
        self._skills = skill_registry
        self._connect_timeout = connect_timeout

        # server_id → MCPClient or MCPStdioClient (duck-typed interface)
        self._clients: dict[int, Any] = {}
        # server_id → list[MCPRemoteToolSkill]
        self._adapters: dict[int, list[MCPRemoteToolSkill]] = {}
        self._running = False

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect all enabled servers in parallel (non-blocking)."""
        self._running = True
        rows = self._store.list_enabled()
        if not rows:
            logger.debug("MCPClientRegistry: no enabled servers to connect")
            return

        tasks = [
            asyncio.create_task(self._connect_one(row), name=f"mcp-connect-{row['name']}")
            for row in rows
        ]
        # Wait for all, but don't let one failure cancel others
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for row, exc in zip(rows, results):
            if isinstance(exc, Exception):
                logger.warning(
                    "MCPClientRegistry: %r failed to connect: %s",
                    row["name"],
                    exc,
                )

    async def stop(self) -> None:
        """Unregister all tool adapters and close all client sessions."""
        self._running = False
        # Unregister adapters
        for server_id, adapters in list(self._adapters.items()):
            for adapter in adapters:
                self._skills.unregister(adapter.name)
        self._adapters.clear()
        # Close clients
        close_tasks = [
            asyncio.create_task(client.close())
            for client in self._clients.values()
        ]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self._clients.clear()
        logger.info("MCPClientRegistry stopped")

    # ── Internal connect logic ────────────────────────────────────────────

    async def _connect_one(self, row: dict[str, Any]) -> None:
        """Connect one server and register its tools.  Must not raise."""
        server_id: int = row["id"]
        name: str = row["name"]
        transport: str = (row.get("transport") or "http").lower()
        allowlist: list[str] = row.get("tool_allowlist") or []

        client: Any
        if transport == "stdio":
            command = row.get("command") or ""
            if not command:
                self._store.set_status(server_id, "error", "stdio server has no command")
                logger.warning("MCPClientRegistry: %r is stdio but has no command", name)
                return
            env = self._secrets.get_env(name)
            client = MCPStdioClient(
                name,
                command,
                args=row.get("args") or [],
                env=env or None,
                timeout=self._connect_timeout,
            )
        else:
            url: str = row.get("url") or ""
            headers = self._secrets.get_headers(name)
            client = MCPClient(
                name,
                url,
                headers=headers or None,
                timeout=self._connect_timeout,
            )
        try:
            await client.connect()
            tools = await client.list_tools()
        except MCPClientError as exc:
            self._store.set_status(server_id, "error", str(exc))
            logger.warning("MCPClientRegistry: %r connect failed: %s", name, exc)
            await client.close()
            return
        except Exception as exc:
            self._store.set_status(server_id, "error", str(exc))
            logger.exception("MCPClientRegistry: unexpected error for %r", name)
            await client.close()
            return

        # Apply tool allow-list
        if allowlist:
            tools = [t for t in tools if t.get("name") in allowlist]

        adapters: list[MCPRemoteToolSkill] = []
        for tool_def in tools:
            adapter = MCPRemoteToolSkill(client, tool_def, name)
            # Resolve name collisions with a numeric suffix
            base_name = adapter.name
            suffix = 2
            while adapter.name in self._skills.names():
                adapter.name = f"{base_name}_{suffix}"
                suffix += 1
                if suffix > 99:
                    logger.warning(
                        "MCPClientRegistry: too many collisions for %r, skipping",
                        base_name,
                    )
                    break
            else:
                try:
                    self._skills.register(adapter)
                    adapters.append(adapter)
                except ValueError as exc:
                    logger.warning("MCPClientRegistry: register %r failed: %s", adapter.name, exc)

        self._clients[server_id] = client
        self._adapters[server_id] = adapters
        self._store.set_status(server_id, "connected")
        logger.info(
            "MCPClientRegistry: %r connected, %d tools registered",
            name,
            len(adapters),
        )

    def _disconnect_one(self, server_id: int) -> None:
        """Synchronously unregister adapters (call before async close)."""
        for adapter in self._adapters.pop(server_id, []):
            self._skills.unregister(adapter.name)

    # ── Hot-reload API ────────────────────────────────────────────────────

    async def add_server(self, row: dict[str, Any]) -> None:
        """Connect a newly-added server and register its tools."""
        await self._connect_one(row)

    async def remove_server(self, server_id: int) -> None:
        """Disconnect a server and unregister all its tool adapters."""
        self._disconnect_one(server_id)
        client = self._clients.pop(server_id, None)
        if client:
            await client.close()

    async def refresh_one(self, server_id: int) -> None:
        """Re-connect a server (e.g. after URL/header change)."""
        await self.remove_server(server_id)
        row = self._store.get(server_id)
        if row and row.get("enabled"):
            await self._connect_one(row)

    # ── Status / introspection ────────────────────────────────────────────

    def get_status(self, server_id: int) -> dict[str, Any]:
        """Return live status dict for the UI."""
        row = self._store.get(server_id) or {}
        client = self._clients.get(server_id)
        adapters = self._adapters.get(server_id, [])
        return {
            "id": server_id,
            "connected": client is not None and not (client.unhealthy if client else True),
            "unhealthy": client.unhealthy if client else False,
            "tool_count": len(adapters),
            "last_status": row.get("last_status"),
            "last_error": row.get("last_error"),
        }

    def list_tool_names(self, server_id: int) -> list[str]:
        """Return full prefixed tool names registered for *server_id*."""
        return [a.name for a in self._adapters.get(server_id, [])]

    def all_tool_names(self) -> list[str]:
        """Return all external tool names currently registered."""
        names = []
        for adapters in self._adapters.values():
            names.extend(a.name for a in adapters)
        return names
