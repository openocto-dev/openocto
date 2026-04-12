"""Tests for the tool-use loop in Claude and OpenAI-compat backends.

We mock the SDKs entirely — these tests verify our loop logic, not the
SDKs themselves.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from openocto.skills.base import Skill, SkillRegistry


class _AddParams(BaseModel):
    a: int
    b: int


class AddSkill(Skill):
    name = "add"
    description = "Add two numbers"
    Parameters = _AddParams

    async def execute(self, a: int, b: int) -> str:
        return str(a + b)


@pytest.fixture
def registry():
    r = SkillRegistry()
    r.register(AddSkill())
    return r


# ── Claude backend ──────────────────────────────────────────────────


def _claude_text_response(text: str):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason="end_turn")


def _claude_tool_use_response(tool_id: str, name: str, inputs: dict):
    block = SimpleNamespace(type="tool_use", id=tool_id, name=name, input=inputs)
    return SimpleNamespace(content=[block], stop_reason="tool_use")


@pytest.fixture
def claude_backend():
    from openocto.ai.claude import ClaudeBackend
    from openocto.config import ClaudeConfig

    with patch("openocto.ai.claude.anthropic.AsyncAnthropic"):
        backend = ClaudeBackend(ClaudeConfig(api_key="sk-test", model="x"))
    backend._client = MagicMock()
    backend._client.messages = MagicMock()
    backend._client.messages.create = AsyncMock()
    return backend


class TestClaudeToolLoop:
    async def test_no_tool_use_returns_text(self, claude_backend, registry):
        claude_backend._client.messages.create.return_value = _claude_text_response("hello")
        result = await claude_backend.send([], "sys", skills=registry)
        assert result == "hello"

    async def test_single_tool_call_then_final_text(self, claude_backend, registry):
        claude_backend._client.messages.create.side_effect = [
            _claude_tool_use_response("tu_1", "add", {"a": 2, "b": 3}),
            _claude_text_response("the answer is 5"),
        ]
        result = await claude_backend.send(
            [{"role": "user", "content": "what is 2+3"}],
            "sys",
            skills=registry,
        )
        assert "5" in result
        assert claude_backend._client.messages.create.call_count == 2

        # Second call should include the tool result block
        second_call_messages = claude_backend._client.messages.create.call_args_list[1].kwargs["messages"]
        assert any(
            isinstance(m["content"], list)
            and any(b.get("type") == "tool_result" for b in m["content"])
            for m in second_call_messages
        )

    async def test_unknown_tool_returns_error_to_model(self, claude_backend, registry):
        claude_backend._client.messages.create.side_effect = [
            _claude_tool_use_response("tu_1", "nonexistent", {}),
            _claude_text_response("ok done"),
        ]
        await claude_backend.send([], "sys", skills=registry)
        second_call_messages = claude_backend._client.messages.create.call_args_list[1].kwargs["messages"]
        tool_result = next(
            b for m in second_call_messages
            if isinstance(m["content"], list)
            for b in m["content"] if b.get("type") == "tool_result"
        )
        assert "Error" in tool_result["content"]

    async def test_skips_loop_when_no_skills(self, claude_backend):
        claude_backend._client.messages.create.return_value = _claude_text_response("hi")
        result = await claude_backend.send([], "sys", skills=None)
        assert result == "hi"
        # Called without `tools=`
        kwargs = claude_backend._client.messages.create.call_args.kwargs
        assert "tools" not in kwargs


# ── OpenAI-compat backend ───────────────────────────────────────────


def _openai_text_response(text: str):
    msg = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _openai_tool_response(tool_id: str, name: str, args_json: str):
    fn = SimpleNamespace(name=name, arguments=args_json)
    tc = SimpleNamespace(id=tool_id, function=fn)
    msg = SimpleNamespace(content="", tool_calls=[tc])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.fixture
def openai_backend():
    from openocto.ai.openai_compat import OpenAICompatBackend

    with patch("openocto.ai.openai_compat.openai.AsyncOpenAI"):
        backend = OpenAICompatBackend(
            name="test", model="gpt-x", base_url="http://x", api_key="k",
        )
    backend._client = MagicMock()
    backend._client.chat = MagicMock()
    backend._client.chat.completions = MagicMock()
    backend._client.chat.completions.create = AsyncMock()
    return backend


class TestOpenAIToolLoop:
    async def test_no_tool_call_returns_text(self, openai_backend, registry):
        openai_backend._client.chat.completions.create.return_value = _openai_text_response("hello")
        result = await openai_backend.send([], "sys", skills=registry)
        assert result == "hello"

    async def test_single_tool_call_loop(self, openai_backend, registry):
        openai_backend._client.chat.completions.create.side_effect = [
            _openai_tool_response("call_1", "add", '{"a": 4, "b": 5}'),
            _openai_text_response("result is 9"),
        ]
        result = await openai_backend.send(
            [{"role": "user", "content": "4 + 5"}], "sys", skills=registry,
        )
        assert "9" in result
        assert openai_backend._client.chat.completions.create.call_count == 2

        # Verify the tool result was injected
        second_messages = openai_backend._client.chat.completions.create.call_args_list[1].kwargs["messages"]
        tool_msgs = [m for m in second_messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == "9"
        assert tool_msgs[0]["tool_call_id"] == "call_1"

    async def test_invalid_json_args_yields_error(self, openai_backend, registry):
        openai_backend._client.chat.completions.create.side_effect = [
            _openai_tool_response("call_1", "add", "not-json"),
            _openai_text_response("ok"),
        ]
        await openai_backend.send([], "sys", skills=registry)
        second_messages = openai_backend._client.chat.completions.create.call_args_list[1].kwargs["messages"]
        tool_msg = next(m for m in second_messages if m.get("role") == "tool")
        assert "Error" in tool_msg["content"]

    async def test_no_skills_skips_tools_param(self, openai_backend):
        openai_backend._client.chat.completions.create.return_value = _openai_text_response("hi")
        await openai_backend.send([], "sys", skills=None)
        kwargs = openai_backend._client.chat.completions.create.call_args.kwargs
        assert "tools" not in kwargs
