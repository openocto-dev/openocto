"""Minimal MCP HTTP client — JSON-RPC 2.0 over Streamable HTTP.

Implements the MCP 2024-11-05 protocol transport sufficient for:

* ``initialize`` handshake
* ``notifications/initialized`` notification
* ``tools/list``
* ``tools/call``

SSE (text/event-stream) responses are *not* supported in v1 — if a server
responds with SSE we raise :class:`MCPTransportError` with a clear message.

Usage::

    client = MCPClient("notion", "https://mcp.notion.com/mcp",
                       headers={"Authorization": "Bearer ntn_xxx"})
    await client.connect()
    tools = await client.list_tools()
    result = await client.call_tool("search", {"query": "python"})
    await client.close()

Authorization headers are **never** logged — they are scrubbed in
:meth:`_rpc` before any log output.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = (0.5, 1.0, 2.0)


# ── Exceptions ────────────────────────────────────────────────────────────────


class MCPClientError(Exception):
    """Base exception for all MCP client errors."""


class MCPTransportError(MCPClientError):
    """HTTP / network level error (non-2xx, timeout, etc.)."""


class MCPProtocolError(MCPClientError):
    """JSON-RPC layer error (error response from the server)."""


class MCPNotConnected(MCPClientError):
    """Operation attempted before :meth:`MCPClient.connect` was called."""


# ── Client ────────────────────────────────────────────────────────────────────


def _scrub_auth(headers: dict[str, str]) -> dict[str, str]:
    """Return headers with Authorization value redacted (for logging)."""
    return {
        k: ("Bearer ****" if k.lower() == "authorization" else v)
        for k, v in headers.items()
    }


class MCPClient:
    """Async MCP client — one instance per external MCP server.

    Thread-safety: designed for use within a single asyncio event loop.
    """

    def __init__(
        self,
        name: str,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._name = name
        self._url = url.rstrip("/")
        self._custom_headers: dict[str, str] = dict(headers or {})
        self._timeout = timeout

        self._session: Any = None  # aiohttp.ClientSession, lazy
        self._session_id: str | None = None
        self._next_rpc_id: int = 1
        self._tools: list[dict[str, Any]] = []
        self.unhealthy: bool = False

    # ── Internal helpers ──────────────────────────────────────────────────

    def _new_id(self) -> int:
        rpc_id = self._next_rpc_id
        self._next_rpc_id += 1
        return rpc_id

    def _build_headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        h.update(self._custom_headers)
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    async def _get_session(self) -> Any:
        if self._session is None:
            try:
                import aiohttp
            except ImportError as exc:
                raise MCPTransportError("aiohttp is required for MCPClient") from exc
            self._session = aiohttp.ClientSession()
        return self._session

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        notification: bool = False,
    ) -> Any:
        """Send a JSON-RPC 2.0 request and return the ``result`` field.

        If *notification* is True the call has no ``id`` and the server
        sends no response (fire-and-forget).

        Raises :class:`MCPTransportError` on HTTP/network errors and
        :class:`MCPProtocolError` on JSON-RPC level errors.
        """
        try:
            import aiohttp
        except ImportError as exc:
            raise MCPTransportError("aiohttp is required for MCPClient") from exc

        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if not notification:
            payload["id"] = self._new_id()
        if params:
            payload["params"] = params

        headers = self._build_headers()
        safe_headers = _scrub_auth(headers)
        logger.debug(
            "MCPClient[%s] → %s (headers: %s)",
            self._name,
            method,
            safe_headers,
        )

        session = await self._get_session()
        try:
            async with session.post(
                self._url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                # Capture session id on every response
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid

                if resp.status >= 400:
                    body = await resp.text()
                    raise MCPTransportError(
                        f"MCPClient[{self._name}] HTTP {resp.status}: {body[:200]}"
                    )

                # SSE not supported in v1
                ct = resp.headers.get("Content-Type", "")
                if "text/event-stream" in ct:
                    raise MCPTransportError(
                        f"MCPClient[{self._name}]: server returned SSE "
                        "(text/event-stream). SSE responses are not supported "
                        "in this version. The server must return JSON."
                    )

                if notification:
                    return None

                data = await resp.json(content_type=None)

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise MCPTransportError(
                f"MCPClient[{self._name}] network error: {exc}"
            ) from exc

        if "error" in data:
            err = data["error"]
            raise MCPProtocolError(
                f"MCPClient[{self._name}] JSON-RPC error {err.get('code')}: "
                f"{err.get('message')}"
            )

        return data.get("result")

    # ── Public API ────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Perform the MCP initialize handshake with exponential back-off.

        Must be called before :meth:`list_tools` or :meth:`call_tool`.
        Retries up to 3 times (0.5 s, 1 s, 2 s delays).
        """
        from openocto import __version__

        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS, None)):  # type: ignore[misc]
            try:
                result = await self._rpc(
                    "initialize",
                    params={
                        "clientInfo": {"name": "openocto", "version": __version__},
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                    },
                )
                logger.debug(
                    "MCPClient[%s] initialized: %s", self._name, result
                )
                # Send the required notifications/initialized (no response expected)
                await self._rpc("notifications/initialized", notification=True)
                self.unhealthy = False
                logger.info("MCPClient[%s] connected to %s", self._name, self._url)
                return

            except MCPClientError as exc:
                last_exc = exc
                if delay is not None:
                    logger.debug(
                        "MCPClient[%s] connect attempt %d failed, retrying in %ss: %s",
                        self._name,
                        attempt + 1,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        self.unhealthy = True
        raise MCPTransportError(
            f"MCPClient[{self._name}] failed to connect after {_MAX_RETRIES} attempts"
        ) from last_exc

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return the server's tool definitions (cached after first call).

        Raises :class:`MCPNotConnected` if :meth:`connect` was never called
        (i.e. no session_id established yet AND no tools cached).
        """
        if self._tools:
            return self._tools
        if self._session is None:
            raise MCPNotConnected(
                f"MCPClient[{self._name}]: call connect() before list_tools()"
            )
        result = await self._rpc("tools/list")
        self._tools = result.get("tools", []) if isinstance(result, dict) else []
        logger.debug(
            "MCPClient[%s] discovered %d tools", self._name, len(self._tools)
        )
        return self._tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke a tool on the remote server and return the raw MCP result dict.

        The caller (adapter) is responsible for extracting ``content[].text``.

        Raises :class:`MCPTransportError` or :class:`MCPProtocolError` on error.
        """
        result = await self._rpc(
            "tools/call",
            params={"name": tool_name, "arguments": arguments or {}},
        )
        return result if isinstance(result, dict) else {"content": [], "isError": False}

    async def reconnect(self) -> None:
        """Re-run the handshake (resets session_id and cached tools)."""
        self._session_id = None
        self._tools = []
        await self.connect()

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
        self._session_id = None
        self._tools = []
        logger.debug("MCPClient[%s] closed", self._name)


# ── Stdio client ──────────────────────────────────────────────────────────────


def _scrub_env(env: dict[str, str]) -> dict[str, str]:
    """Return env dict with values masked (for logging)."""
    return {k: "****" for k in env}


class MCPStdioClient:
    """MCP client that speaks JSON-RPC over a child process stdin/stdout.

    Compatible surface with :class:`MCPClient` so the registry can pick
    either at runtime:

    * ``connect()``, ``list_tools()``, ``call_tool()``, ``close()``
    * ``unhealthy`` flag
    * ``name`` attribute

    The child process is launched via :func:`asyncio.create_subprocess_exec`.
    Each JSON-RPC request is serialised, sent as one line to stdin, and the
    matching response is read back line-by-line from stdout. Notifications
    received from the server are silently discarded — v1 does not propagate
    server-initiated events into the rest of OpenOcto.
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._name = name
        self.name = name  # public attr so registry can treat it like MCPClient
        self._command = command
        self._args = list(args or [])
        self._env = dict(env or {})
        self._timeout = timeout

        self._proc: asyncio.subprocess.Process | None = None
        self._next_rpc_id: int = 1
        self._tools: list[dict[str, Any]] = []
        self._io_lock = asyncio.Lock()
        self._stderr_task: asyncio.Task | None = None
        self.unhealthy: bool = False

    def _new_id(self) -> int:
        rpc_id = self._next_rpc_id
        self._next_rpc_id += 1
        return rpc_id

    async def _drain_stderr(self) -> None:
        """Background task: read stderr and log it at DEBUG level."""
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    return
                logger.debug(
                    "MCPStdioClient[%s] stderr: %s",
                    self._name,
                    line.decode("utf-8", errors="replace").rstrip(),
                )
        except Exception:
            return

    async def _spawn(self) -> None:
        if self._proc and self._proc.returncode is None:
            return
        # Merge user env over current environment so PATH etc. still work
        child_env = {**os.environ, **self._env}
        logger.debug(
            "MCPStdioClient[%s] spawning %s %s (env keys: %s)",
            self._name,
            self._command,
            self._args,
            list(_scrub_env(self._env).keys()),
        )
        try:
            # limit = per-line StreamReader buffer for stdout/stderr.
            # Default (64 KB) is too small — MCP tools/list responses often
            # exceed that for servers with many tools/schemas (e.g. Plane).
            # 1 MB is ~16x the default and big enough for any realistic
            # JSON-RPC response while still acting as a sanity guard.
            self._proc = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=child_env,
                limit=1024 * 1024,
            )
        except FileNotFoundError as exc:
            raise MCPTransportError(
                f"MCPStdioClient[{self._name}]: command not found: {self._command}"
            ) from exc
        except Exception as exc:
            raise MCPTransportError(
                f"MCPStdioClient[{self._name}]: failed to spawn: {exc}"
            ) from exc

        self._stderr_task = asyncio.create_task(
            self._drain_stderr(), name=f"mcp-stderr-{self._name}"
        )

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        notification: bool = False,
    ) -> Any:
        """Write one JSON-RPC request and read the matching response line."""
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise MCPNotConnected(
                f"MCPStdioClient[{self._name}]: connect() not called"
            )
        if self._proc.returncode is not None:
            raise MCPTransportError(
                f"MCPStdioClient[{self._name}]: child process exited "
                f"(code {self._proc.returncode})"
            )

        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notification:
            payload["id"] = self._new_id()
        if params:
            payload["params"] = params

        line = (json.dumps(payload) + "\n").encode("utf-8")
        logger.debug("MCPStdioClient[%s] → %s", self._name, method)

        async with self._io_lock:
            try:
                self._proc.stdin.write(line)
                await self._proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise MCPTransportError(
                    f"MCPStdioClient[{self._name}] stdin closed: {exc}"
                ) from exc

            if notification:
                return None

            # Read lines until we get a response with matching id
            req_id = payload["id"]
            try:
                while True:
                    raw = await asyncio.wait_for(
                        self._proc.stdout.readline(), timeout=self._timeout
                    )
                    if not raw:
                        raise MCPTransportError(
                            f"MCPStdioClient[{self._name}] stdout closed mid-request"
                        )
                    try:
                        msg = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        logger.debug(
                            "MCPStdioClient[%s] non-JSON stdout line: %r",
                            self._name,
                            raw[:200],
                        )
                        continue
                    # Skip notifications (no id) from server
                    if "id" not in msg:
                        continue
                    if msg.get("id") != req_id:
                        # Out-of-order response — shouldn't happen with our lock
                        logger.debug(
                            "MCPStdioClient[%s] ignoring id=%s (expected %s)",
                            self._name,
                            msg.get("id"),
                            req_id,
                        )
                        continue
                    break
            except asyncio.TimeoutError as exc:
                raise MCPTransportError(
                    f"MCPStdioClient[{self._name}] timeout waiting for {method}"
                ) from exc

        if "error" in msg:
            err = msg["error"]
            raise MCPProtocolError(
                f"MCPStdioClient[{self._name}] JSON-RPC error "
                f"{err.get('code')}: {err.get('message')}"
            )
        return msg.get("result")

    # ── Public API (mirrors MCPClient) ────────────────────────────────────

    async def connect(self) -> None:
        from openocto import __version__

        await self._spawn()
        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS, None)):
            try:
                await self._rpc(
                    "initialize",
                    params={
                        "clientInfo": {"name": "openocto", "version": __version__},
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                    },
                )
                await self._rpc("notifications/initialized", notification=True)
                self.unhealthy = False
                logger.info(
                    "MCPStdioClient[%s] connected (pid=%s)",
                    self._name,
                    self._proc.pid if self._proc else "?",
                )
                return
            except MCPClientError as exc:
                last_exc = exc
                if delay is not None:
                    logger.debug(
                        "MCPStdioClient[%s] connect attempt %d failed: %s",
                        self._name,
                        attempt + 1,
                        exc,
                    )
                    await asyncio.sleep(delay)

        self.unhealthy = True
        raise MCPTransportError(
            f"MCPStdioClient[{self._name}] failed to connect after {_MAX_RETRIES} attempts"
        ) from last_exc

    async def list_tools(self) -> list[dict[str, Any]]:
        if self._tools:
            return self._tools
        if self._proc is None:
            raise MCPNotConnected(
                f"MCPStdioClient[{self._name}]: call connect() first"
            )
        result = await self._rpc("tools/list")
        self._tools = result.get("tools", []) if isinstance(result, dict) else []
        logger.debug(
            "MCPStdioClient[%s] discovered %d tools", self._name, len(self._tools)
        )
        return self._tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await self._rpc(
            "tools/call",
            params={"name": tool_name, "arguments": arguments or {}},
        )
        return result if isinstance(result, dict) else {"content": [], "isError": False}

    async def reconnect(self) -> None:
        await self.close()
        await self.connect()

    async def close(self) -> None:
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass
        self._stderr_task = None
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    try:
                        self._proc.stdin.close()
                    except Exception:
                        pass
                if self._proc.returncode is None:
                    try:
                        await asyncio.wait_for(self._proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        self._proc.kill()
                        try:
                            await self._proc.wait()
                        except Exception:
                            pass
            finally:
                self._proc = None
        self._tools = []
        logger.debug("MCPStdioClient[%s] closed", self._name)
