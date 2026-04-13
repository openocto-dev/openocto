"""Tests for MCPClient, MCPRemoteToolSkill (adapter), and MCPClientRegistry.

aiohttp.ClientSession.post is patched via AsyncMock so no real network
connections are made.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openocto.mcp_client.client import (
    MCPClient,
    MCPClientError,
    MCPNotConnected,
    MCPProtocolError,
    MCPTransportError,
)
from openocto.mcp_client.adapter import MCPRemoteToolSkill, _sanitize_name
from openocto.mcp_client.registry import MCPClientRegistry
from openocto.mcp_client.secrets import MCPSecretsStore
from openocto.mcp_client.store import MCPServerStore
from openocto.skills.base import SkillRegistry


# ── Fixtures ──────────────────────────────────────────────────────────────────

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS mcp_servers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT UNIQUE NOT NULL,
    url                 TEXT NOT NULL DEFAULT '',
    transport           TEXT NOT NULL DEFAULT 'http',
    command             TEXT,
    args_json           TEXT NOT NULL DEFAULT '[]',
    tool_allowlist_json TEXT NOT NULL DEFAULT '[]',
    enabled             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    last_status         TEXT,
    last_error          TEXT,
    last_checked_at     TEXT
);
"""


@pytest.fixture()
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    yield conn
    conn.close()


@pytest.fixture()
def store(db_conn):
    return MCPServerStore(db_conn)


@pytest.fixture()
def secrets(tmp_path: Path):
    return MCPSecretsStore(tmp_path / "mcp-secrets.yaml")


@pytest.fixture()
def skill_registry():
    return SkillRegistry()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_response(result=None, error=None, session_id=None, content_type="application/json"):
    """Build a mock aiohttp response."""
    body: dict = {"jsonrpc": "2.0", "id": 1}
    if error:
        body["error"] = error
    else:
        body["result"] = result

    resp = AsyncMock()
    resp.status = 200
    resp.headers = {"Content-Type": content_type}
    if session_id:
        resp.headers["Mcp-Session-Id"] = session_id
    resp.json = AsyncMock(return_value=body)
    resp.text = AsyncMock(return_value=json.dumps(body))
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_client(name="test", url="http://mcp.example.com/mcp", headers=None):
    return MCPClient(name, url, headers=headers, timeout=5.0)


# ── MCPClient tests ───────────────────────────────────────────────────────────


class TestMCPClientConnect:
    @pytest.mark.asyncio
    async def test_connect_handshake(self):
        init_resp = _make_response(
            result={"protocolVersion": "2024-11-05", "capabilities": {}},
            session_id="sess-abc",
        )
        notif_resp = _make_response(result=None)

        client = _make_client()

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.side_effect = [init_resp, notif_resp]
            await client.connect()

        assert client._session_id == "sess-abc"
        assert not client.unhealthy
        # Two calls: initialize + notifications/initialized
        assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_connect_retries_then_succeeds(self):
        error_resp = AsyncMock()
        error_resp.status = 503
        error_resp.headers = {"Content-Type": "application/json"}
        error_resp.text = AsyncMock(return_value="Service unavailable")
        error_resp.__aenter__ = AsyncMock(return_value=error_resp)
        error_resp.__aexit__ = AsyncMock(return_value=False)

        ok_init = _make_response(result={"protocolVersion": "2024-11-05"})
        ok_notif = _make_response(result=None)

        client = _make_client()
        with patch("aiohttp.ClientSession.post") as mock_post, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_post.side_effect = [error_resp, ok_init, ok_notif]
            await client.connect()

        assert not client.unhealthy

    @pytest.mark.asyncio
    async def test_connect_fails_after_max_retries(self):
        error_resp = AsyncMock()
        error_resp.status = 503
        error_resp.headers = {"Content-Type": "application/json"}
        error_resp.text = AsyncMock(return_value="down")
        error_resp.__aenter__ = AsyncMock(return_value=error_resp)
        error_resp.__aexit__ = AsyncMock(return_value=False)

        client = _make_client()
        with patch("aiohttp.ClientSession.post") as mock_post, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_post.return_value = error_resp
            with pytest.raises(MCPTransportError):
                await client.connect()

        assert client.unhealthy


class TestMCPClientListTools:
    @pytest.mark.asyncio
    async def test_list_tools_requires_connect(self):
        client = _make_client()
        with pytest.raises(MCPNotConnected):
            await client.list_tools()

    @pytest.mark.asyncio
    async def test_list_tools_returns_array(self):
        init_resp = _make_response(result={"protocolVersion": "2024-11-05"})
        notif_resp = _make_response(result=None)
        tools_resp = _make_response(result={
            "tools": [
                {"name": "search", "description": "Search", "inputSchema": {}},
                {"name": "create_page", "description": "Create", "inputSchema": {}},
            ]
        })

        client = _make_client()
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.side_effect = [init_resp, notif_resp, tools_resp]
            await client.connect()
            tools = await client.list_tools()

        assert len(tools) == 2
        assert tools[0]["name"] == "search"

    @pytest.mark.asyncio
    async def test_list_tools_cached_after_first_call(self):
        init_resp = _make_response(result={"protocolVersion": "2024-11-05"})
        notif_resp = _make_response(result=None)
        tools_resp = _make_response(result={"tools": [{"name": "t1", "description": "", "inputSchema": {}}]})

        client = _make_client()
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.side_effect = [init_resp, notif_resp, tools_resp]
            await client.connect()
            tools1 = await client.list_tools()
            tools2 = await client.list_tools()  # should use cache, no extra call

        assert tools1 == tools2
        assert mock_post.call_count == 3  # init + notif + one tools/list


class TestMCPClientCallTool:
    @pytest.mark.asyncio
    async def test_call_tool_round_trip(self):
        call_resp = _make_response(result={
            "content": [{"type": "text", "text": "result text"}],
            "isError": False,
        })
        client = _make_client()
        # inject a mock session so _get_session() doesn't create a real one
        mock_session = MagicMock()
        mock_session.post.return_value = call_resp
        client._session = mock_session

        result = await client.call_tool("search", {"query": "python"})

        assert result["content"][0]["text"] == "result text"

    @pytest.mark.asyncio
    async def test_call_tool_rpc_error_raises_protocol_error(self):
        error_resp = _make_response(error={"code": -32600, "message": "Invalid request"})
        client = _make_client()
        mock_session = MagicMock()
        mock_session.post.return_value = error_resp
        client._session = mock_session

        with pytest.raises(MCPProtocolError):
            await client.call_tool("bad_tool", {})


class TestMCPClientSSE:
    @pytest.mark.asyncio
    async def test_sse_response_raises(self):
        sse_resp = AsyncMock()
        sse_resp.status = 200
        sse_resp.headers = {"Content-Type": "text/event-stream"}
        sse_resp.__aenter__ = AsyncMock(return_value=sse_resp)
        sse_resp.__aexit__ = AsyncMock(return_value=False)

        client = _make_client()
        mock_session = MagicMock()
        mock_session.post.return_value = sse_resp
        client._session = mock_session

        with pytest.raises(MCPTransportError, match="SSE"):
            await client._rpc("tools/list")


class TestMCPClientSessionId:
    @pytest.mark.asyncio
    async def test_session_id_sent_on_subsequent_requests(self):
        init_resp = _make_response(result={"protocolVersion": "2024-11-05"}, session_id="my-session")
        notif_resp = _make_response(result=None)
        tools_resp = _make_response(result={"tools": []})

        client = _make_client()
        captured_headers = []

        original_post = None

        def patched_post(url, *, json=None, headers=None, timeout=None):
            captured_headers.append(dict(headers or {}))
            if len(captured_headers) == 1:
                return init_resp
            elif len(captured_headers) == 2:
                return notif_resp
            return tools_resp

        with patch("aiohttp.ClientSession.post", side_effect=patched_post):
            await client.connect()
            await client.list_tools()

        # Third call (tools/list) should include session id
        assert captured_headers[2].get("Mcp-Session-Id") == "my-session"


class TestMCPClientClose:
    @pytest.mark.asyncio
    async def test_close_resets_state(self):
        client = _make_client()
        client._session = AsyncMock()
        client._session.close = AsyncMock()
        client._session_id = "sess"
        client._tools = [{"name": "t1"}]

        await client.close()

        assert client._session is None
        assert client._session_id is None
        assert client._tools == []


class TestAuthHeaderScrubbing:
    @pytest.mark.asyncio
    async def test_authorization_scrubbed_from_logs(self, caplog):
        """The real bearer token must NOT appear in any log output."""
        import logging
        from openocto.mcp_client.client import _scrub_auth

        headers = {"Authorization": "Bearer super_secret_token", "X-Other": "value"}
        scrubbed = _scrub_auth(headers)
        assert "super_secret_token" not in scrubbed["Authorization"]
        assert "Bearer ****" == scrubbed["Authorization"]
        assert scrubbed["X-Other"] == "value"


# ── MCPRemoteToolSkill (adapter) tests ────────────────────────────────────────


class TestAdapterName:
    def test_name_prefixing(self):
        client = MagicMock()
        tool = {"name": "create_page", "description": "Create a page", "inputSchema": {}}
        adapter = MCPRemoteToolSkill(client, tool, "notion")
        assert adapter.name == "notion__create_page"

    def test_name_sanitization_hyphens(self):
        result = _sanitize_name("notion__create-page")
        assert result == "notion__create_page"

    def test_name_sanitization_uppercase(self):
        result = _sanitize_name("Notion__CreatePage")
        assert result == "notion__createpage"

    def test_name_sanitization_dots(self):
        result = _sanitize_name("server.v2__tool.name")
        assert result == "server_v2__tool_name"

    def test_name_truncation(self):
        long_name = "a" * 100
        result = _sanitize_name(long_name)
        assert len(result) <= 64

    def test_description_prefixed_with_server(self):
        client = MagicMock()
        tool = {"name": "search", "description": "Search pages", "inputSchema": {}}
        adapter = MCPRemoteToolSkill(client, tool, "notion")
        assert adapter.description.startswith("[notion]")
        assert "Search pages" in adapter.description

    def test_schema_passthrough(self):
        client = MagicMock()
        schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        tool = {"name": "search", "inputSchema": schema}
        adapter = MCPRemoteToolSkill(client, tool, "notion")
        assert adapter._input_schema == schema
        assert adapter.to_anthropic_tool()["input_schema"] == schema
        assert adapter.to_openai_tool()["function"]["parameters"] == schema
        assert adapter.to_mcp_tool()["inputSchema"] == schema


class TestAdapterExecute:
    @pytest.mark.asyncio
    async def test_execute_success_extracts_text(self):
        client = AsyncMock()
        client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}],
            "isError": False,
        })
        tool = {"name": "greet", "inputSchema": {}}
        adapter = MCPRemoteToolSkill(client, tool, "myserver")
        result = await adapter.execute(name="Octo")
        assert "hello" in result
        assert "world" in result

    @pytest.mark.asyncio
    async def test_execute_is_error_flag(self):
        client = AsyncMock()
        client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "something went wrong"}],
            "isError": True,
        })
        tool = {"name": "fail_tool", "inputSchema": {}}
        adapter = MCPRemoteToolSkill(client, tool, "myserver")
        result = await adapter.execute()
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_execute_transport_error_raises_skill_error_and_marks_unhealthy(self):
        from openocto.mcp_client.client import MCPTransportError
        from openocto.skills.base import SkillError

        client = AsyncMock()
        client.unhealthy = False
        client.call_tool = AsyncMock(side_effect=MCPTransportError("connection reset"))
        tool = {"name": "t", "inputSchema": {}}
        adapter = MCPRemoteToolSkill(client, tool, "myserver")

        with pytest.raises(SkillError):
            await adapter.execute()

        assert client.unhealthy is True


# ── SkillRegistry extensions ──────────────────────────────────────────────────


class TestSkillRegistryExtensions:
    def test_unregister_removes_skill(self, skill_registry):
        client = MagicMock()
        tool = {"name": "greet", "description": "Say hi", "inputSchema": {}}
        adapter = MCPRemoteToolSkill(client, tool, "demo")
        skill_registry.register(adapter)
        assert "demo__greet" in skill_registry.names()
        skill_registry.unregister("demo__greet")
        assert "demo__greet" not in skill_registry.names()

    def test_unregister_noop_for_unknown(self, skill_registry):
        skill_registry.unregister("nonexistent")  # should not raise

    @pytest.mark.asyncio
    async def test_skip_validation_passthrough(self, skill_registry):
        """Skill with _skip_validation=True bypasses pydantic and calls execute directly."""
        client = AsyncMock()
        client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "42"}],
            "isError": False,
        })
        tool = {"name": "answer", "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}}
        adapter = MCPRemoteToolSkill(client, tool, "oracle")
        skill_registry.register(adapter)

        result = await skill_registry.call("oracle__answer", {"q": "life?"})
        assert "42" in result


# ── MCPClientRegistry tests ───────────────────────────────────────────────────


def _make_mock_client(tools=None, fail=False):
    """Return a mock MCPClient."""
    client = AsyncMock()
    client.unhealthy = False
    if fail:
        client.connect = AsyncMock(side_effect=MCPTransportError("connection refused"))
    else:
        client.connect = AsyncMock()
        client.list_tools = AsyncMock(return_value=tools or [
            {"name": "tool_a", "description": "Tool A", "inputSchema": {}},
        ])
    client.close = AsyncMock()
    return client


class TestMCPClientRegistry:
    @pytest.mark.asyncio
    async def test_registry_start_connects_enabled_servers(self, store, secrets, skill_registry):
        store.create("svc", "http://svc.example.com/mcp", enabled=True)

        with patch("openocto.mcp_client.registry.MCPClient") as MockClient:
            mock = _make_mock_client()
            MockClient.return_value = mock
            registry = MCPClientRegistry(store, secrets, skill_registry)
            await registry.start()

        mock.connect.assert_awaited_once()
        assert "svc__tool_a" in skill_registry.names()

    @pytest.mark.asyncio
    async def test_registry_start_skips_disabled(self, store, secrets, skill_registry):
        store.create("svc", "http://svc.example.com/mcp", enabled=False)

        with patch("openocto.mcp_client.registry.MCPClient") as MockClient:
            mock = _make_mock_client()
            MockClient.return_value = mock
            registry = MCPClientRegistry(store, secrets, skill_registry)
            await registry.start()

        mock.connect.assert_not_awaited()
        assert "svc__tool_a" not in skill_registry.names()

    @pytest.mark.asyncio
    async def test_registry_start_isolates_failure(self, store, secrets, skill_registry):
        """Server A fails, server B should still connect."""
        id_a = store.create("fails", "http://a.example.com/mcp", enabled=True)
        id_b = store.create("works", "http://b.example.com/mcp", enabled=True)

        def make_client(name, url, **kwargs):
            if name == "fails":
                return _make_mock_client(fail=True)
            return _make_mock_client(tools=[{"name": "ok_tool", "description": "", "inputSchema": {}}])

        with patch("openocto.mcp_client.registry.MCPClient", side_effect=make_client):
            registry = MCPClientRegistry(store, secrets, skill_registry)
            await registry.start()

        assert "fails__tool_a" not in skill_registry.names()
        assert "works__ok_tool" in skill_registry.names()
        row_a = store.get(id_a)
        assert row_a["last_status"] == "error"

    @pytest.mark.asyncio
    async def test_registry_applies_allowlist(self, store, secrets, skill_registry):
        store.create("svc", "http://svc.example.com/mcp",
                     tool_allowlist=["tool_b"], enabled=True)

        with patch("openocto.mcp_client.registry.MCPClient") as MockClient:
            mock = _make_mock_client(tools=[
                {"name": "tool_a", "description": "", "inputSchema": {}},
                {"name": "tool_b", "description": "", "inputSchema": {}},
            ])
            MockClient.return_value = mock
            registry = MCPClientRegistry(store, secrets, skill_registry)
            await registry.start()

        assert "svc__tool_b" in skill_registry.names()
        assert "svc__tool_a" not in skill_registry.names()

    @pytest.mark.asyncio
    async def test_registry_remove_unregisters_tools(self, store, secrets, skill_registry):
        server_id = store.create("svc", "http://svc.example.com/mcp", enabled=True)

        with patch("openocto.mcp_client.registry.MCPClient") as MockClient:
            MockClient.return_value = _make_mock_client()
            registry = MCPClientRegistry(store, secrets, skill_registry)
            await registry.start()

        assert "svc__tool_a" in skill_registry.names()
        await registry.remove_server(server_id)
        assert "svc__tool_a" not in skill_registry.names()

    @pytest.mark.asyncio
    async def test_registry_stop_closes_all_clients(self, store, secrets, skill_registry):
        store.create("svc1", "http://svc1.example.com/mcp", enabled=True)
        store.create("svc2", "http://svc2.example.com/mcp", enabled=True)

        mock1 = _make_mock_client(tools=[{"name": "t1", "description": "", "inputSchema": {}}])
        mock2 = _make_mock_client(tools=[{"name": "t2", "description": "", "inputSchema": {}}])
        clients_iter = iter([mock1, mock2])

        with patch("openocto.mcp_client.registry.MCPClient", side_effect=lambda *a, **kw: next(clients_iter)):
            registry = MCPClientRegistry(store, secrets, skill_registry)
            await registry.start()
            await registry.stop()

        mock1.close.assert_awaited_once()
        mock2.close.assert_awaited_once()


# ── End-to-end integration ────────────────────────────────────────────────────


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_e2e_tools_visible_in_anthropic_tools(self, store, secrets, skill_registry):
        store.create("oracle", "http://oracle.example.com/mcp", enabled=True)

        with patch("openocto.mcp_client.registry.MCPClient") as MockClient:
            MockClient.return_value = _make_mock_client(tools=[
                {
                    "name": "ask",
                    "description": "Ask the oracle",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"question": {"type": "string"}},
                        "required": ["question"],
                    },
                }
            ])
            registry = MCPClientRegistry(store, secrets, skill_registry)
            await registry.start()

        anthropic_tools = skill_registry.anthropic_tools()
        names = [t["name"] for t in anthropic_tools]
        assert "oracle__ask" in names

        tool = next(t for t in anthropic_tools if t["name"] == "oracle__ask")
        assert "question" in tool["input_schema"]["properties"]

    @pytest.mark.asyncio
    async def test_e2e_unhealthy_server_does_not_break_others(self, store, secrets, skill_registry):
        store.create("bad", "http://bad.example.com/mcp", enabled=True)
        store.create("good", "http://good.example.com/mcp", enabled=True)

        def make(name, url, **kwargs):
            if name == "bad":
                return _make_mock_client(fail=True)
            return _make_mock_client(tools=[{"name": "fine_tool", "description": "", "inputSchema": {}}])

        with patch("openocto.mcp_client.registry.MCPClient", side_effect=make):
            registry = MCPClientRegistry(store, secrets, skill_registry)
            await registry.start()

        assert "good__fine_tool" in skill_registry.names()
        assert skill_registry.get("bad__tool_a") is None
