"""Tests for the MCP server — JSON-RPC dispatch, auth, and tool calling."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_config(require_auth: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        host="127.0.0.1",
        port=8765,
        require_auth=require_auth,
    )


def _make_skill(name: str, result: str = "ok") -> MagicMock:
    skill = MagicMock()
    skill.name = name
    skill.description = f"{name} skill"
    skill.to_mcp_tool.return_value = {
        "name": name,
        "description": f"{name} skill",
        "inputSchema": {"type": "object", "properties": {}},
    }
    return skill


def _make_registry(skills: list) -> MagicMock:
    reg = MagicMock()
    reg.names.return_value = [s.name for s in skills]
    reg.mcp_tools.return_value = [s.to_mcp_tool() for s in skills]
    reg.get.side_effect = lambda name: next((s for s in skills if s.name == name), None)
    reg.call = AsyncMock(return_value="result_text")
    reg.bind_context = MagicMock()
    return reg


def _make_octo(registry=None) -> SimpleNamespace:
    return SimpleNamespace(
        _skills=registry,
        _history_store=None,
        _current_user_id=1,
        _persona=SimpleNamespace(name="octo"),
        _player=None,
    )


# ── Auth tests ────────────────────────────────────────────────────────────────

class TestMCPAuth:
    def test_extract_bearer_valid(self):
        from openocto.mcp.auth import extract_bearer
        assert extract_bearer("Bearer mytoken123") == "mytoken123"

    def test_extract_bearer_none(self):
        from openocto.mcp.auth import extract_bearer
        assert extract_bearer(None) is None
        assert extract_bearer("") is None

    def test_extract_bearer_bad_scheme(self):
        from openocto.mcp.auth import extract_bearer
        assert extract_bearer("Basic abc") is None

    def test_verify_token_match(self):
        from openocto.mcp.auth import verify_token
        assert verify_token("abc123", "abc123") is True

    def test_verify_token_mismatch(self):
        from openocto.mcp.auth import verify_token
        assert verify_token("wrong", "abc123") is False

    def test_verify_token_none(self):
        from openocto.mcp.auth import verify_token
        assert verify_token(None, "abc123") is False


# ── RPC dispatch tests ────────────────────────────────────────────────────────

class TestMCPDispatch:
    """Tests for MCPServer._dispatch — pure async logic, no HTTP."""

    def _make_server(self, registry=None):
        from openocto.mcp.server import MCPServer
        octo = _make_octo(registry)
        server = MCPServer(octo, _make_config(require_auth=False))
        server._token = None
        return server

    @pytest.mark.asyncio
    async def test_initialize(self):
        server = self._make_server()
        result = await server._dispatch({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })
        assert result["id"] == 1
        assert "protocolVersion" in result["result"]
        assert result["result"]["protocolVersion"] == "2024-11-05"

    @pytest.mark.asyncio
    async def test_notifications_initialized_returns_none(self):
        server = self._make_server()
        result = await server._dispatch({
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert result is None

    @pytest.mark.asyncio
    async def test_ping(self):
        server = self._make_server()
        result = await server._dispatch({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        assert result["id"] == 2
        assert result["result"] == {}

    @pytest.mark.asyncio
    async def test_unknown_method(self):
        server = self._make_server()
        result = await server._dispatch({"jsonrpc": "2.0", "id": 3, "method": "nonexistent"})
        assert "error" in result
        assert result["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_not_a_dict(self):
        server = self._make_server()
        result = await server._dispatch("bad")
        assert "error" in result
        assert result["error"]["code"] == -32600

    @pytest.mark.asyncio
    async def test_missing_method(self):
        server = self._make_server()
        result = await server._dispatch({"jsonrpc": "2.0", "id": 4})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_tools_list_empty(self):
        server = self._make_server(registry=None)
        result = await server._dispatch({"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
        assert result["result"]["tools"] == []

    @pytest.mark.asyncio
    async def test_tools_list_with_skills(self):
        registry = _make_registry([_make_skill("time"), _make_skill("weather")])
        server = self._make_server(registry)
        result = await server._dispatch({"jsonrpc": "2.0", "id": 6, "method": "tools/list"})
        names = [t["name"] for t in result["result"]["tools"]]
        assert "time" in names
        assert "weather" in names

    @pytest.mark.asyncio
    async def test_tools_call_success(self):
        registry = _make_registry([_make_skill("time")])
        registry.call = AsyncMock(return_value="14:30 Moscow")
        server = self._make_server(registry)
        result = await server._dispatch({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "time", "arguments": {}},
        })
        assert result["result"]["content"][0]["text"] == "14:30 Moscow"
        assert result["result"]["isError"] is False

    @pytest.mark.asyncio
    async def test_tools_call_error_result(self):
        registry = _make_registry([_make_skill("time")])
        registry.call = AsyncMock(return_value="Error: something went wrong")
        server = self._make_server(registry)
        result = await server._dispatch({
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "time", "arguments": {}},
        })
        assert result["result"]["isError"] is True

    @pytest.mark.asyncio
    async def test_tools_call_unknown_tool(self):
        registry = _make_registry([_make_skill("time")])
        server = self._make_server(registry)
        result = await server._dispatch({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "nonexistent", "arguments": {}},
        })
        assert "error" in result
        assert result["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_tools_call_missing_name(self):
        registry = _make_registry([])
        server = self._make_server(registry)
        result = await server._dispatch({
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {},
        })
        assert "error" in result
        assert result["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_tools_call_no_skills(self):
        server = self._make_server(registry=None)
        result = await server._dispatch({
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": "time"},
        })
        assert "error" in result


# ── MCP tool converter tests ──────────────────────────────────────────────────

class TestSkillMCPConverter:
    def test_to_mcp_tool_shape(self):
        from openocto.skills.time_skill import TimeSkill
        skill = TimeSkill({})
        tool = skill.to_mcp_tool()
        assert tool["name"] == skill.name
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"].get("type") == "object"

    def test_mcp_tools_registry(self):
        from openocto.skills.time_skill import TimeSkill
        from openocto.skills.base import SkillRegistry
        reg = SkillRegistry()
        skill = TimeSkill({})
        reg.register(skill)
        tools = reg.mcp_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == skill.name
        assert "inputSchema" in tools[0]
