"""Tests for the Skill SDK base + registry."""

import pytest
from pydantic import BaseModel

from openocto.skills.base import (
    Skill,
    SkillError,
    SkillRegistry,
    SkillUnavailable,
)


class _EchoParams(BaseModel):
    message: str


class EchoSkill(Skill):
    name = "echo"
    description = "Echo the message back"
    Parameters = _EchoParams

    async def execute(self, message: str) -> str:
        return f"echo: {message}"


class BoomSkill(Skill):
    name = "boom"
    description = "Always raises"
    Parameters = _EchoParams

    async def execute(self, message: str) -> str:
        raise SkillError("kaboom")


class CrashSkill(Skill):
    name = "crash"
    description = "Crashes with a generic exception"
    Parameters = _EchoParams

    async def execute(self, message: str) -> str:
        raise RuntimeError("oops")


class UnavailableSkill(Skill):
    name = "unavail"
    description = "Never registers"
    Parameters = _EchoParams

    def __init__(self, config=None):
        raise SkillUnavailable("missing dependency")

    async def execute(self, **kwargs):
        return "unreachable"


class TestSkillRegistry:
    def test_register_and_lookup(self):
        reg = SkillRegistry()
        reg.register(EchoSkill())
        assert "echo" in reg.names()
        assert reg.get("echo") is not None
        assert len(reg) == 1

    def test_duplicate_registration_raises(self):
        reg = SkillRegistry()
        reg.register(EchoSkill())
        with pytest.raises(ValueError):
            reg.register(EchoSkill())

    def test_try_register_skips_unavailable(self):
        reg = SkillRegistry()
        result = reg.try_register(UnavailableSkill)
        assert result is None
        assert len(reg) == 0

    def test_try_register_succeeds_for_normal_skill(self):
        reg = SkillRegistry()
        result = reg.try_register(EchoSkill)
        assert result is not None
        assert len(reg) == 1

    async def test_call_validates_arguments(self):
        reg = SkillRegistry()
        reg.register(EchoSkill())
        result = await reg.call("echo", {"message": "hi"})
        assert result == "echo: hi"

    async def test_call_unknown_skill_returns_error(self):
        reg = SkillRegistry()
        result = await reg.call("nope", {})
        assert result.startswith("Error:")

    async def test_call_invalid_args_returns_error(self):
        reg = SkillRegistry()
        reg.register(EchoSkill())
        result = await reg.call("echo", {})
        assert result.startswith("Error: invalid arguments")

    async def test_skill_error_is_caught(self):
        reg = SkillRegistry()
        reg.register(BoomSkill())
        result = await reg.call("boom", {"message": "x"})
        assert result == "Error: kaboom"

    async def test_generic_exception_is_caught(self):
        reg = SkillRegistry()
        reg.register(CrashSkill())
        result = await reg.call("crash", {"message": "x"})
        assert result.startswith("Error: crash failed")

    def test_anthropic_tool_format(self):
        reg = SkillRegistry()
        reg.register(EchoSkill())
        tools = reg.anthropic_tools()
        assert len(tools) == 1
        tool = tools[0]
        assert tool["name"] == "echo"
        assert tool["description"] == "Echo the message back"
        assert "input_schema" in tool
        assert "message" in tool["input_schema"]["properties"]

    def test_openai_tool_format(self):
        reg = SkillRegistry()
        reg.register(EchoSkill())
        tools = reg.openai_tools()
        assert len(tools) == 1
        tool = tools[0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "echo"
        assert "parameters" in tool["function"]

    def test_bind_context_propagates(self):
        reg = SkillRegistry()
        skill = EchoSkill()
        reg.register(skill)
        reg.bind_context(user_id=42, persona="octo")
        assert getattr(skill, "_ctx_user_id") == 42
        assert getattr(skill, "_ctx_persona") == "octo"
