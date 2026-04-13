"""Skill SDK — base class, registry, and tool-calling helpers.

A Skill is a callable capability the LLM can invoke via tool use.
Each skill defines:
  * a unique ``name`` (snake_case, used as the tool name);
  * a ``description`` written FOR the LLM — when to call, what it does;
  * a pydantic ``Parameters`` schema describing arguments;
  * an async ``execute(**kwargs)`` returning a string result the LLM
    will see as ``tool_result``.

The dispatcher is the LLM itself.  We translate the registry into the
Anthropic / OpenAI tool format and run a tool-use loop in the AI router.
Skills that depend on missing binaries or unset config raise
``SkillUnavailable`` from ``__init__`` and are silently dropped.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SkillUnavailable(Exception):
    """Raised by a Skill's __init__ when its prerequisites are missing.

    The registry catches this and skips registration without raising.
    """


class SkillError(Exception):
    """Raised inside ``execute`` to surface a user-visible error.

    Caught by the registry; the message is returned to the LLM as the
    tool result so it can react (e.g. ask for clarification).
    """


class Skill(ABC):
    """Abstract base for an LLM-callable capability.

    Subclasses set ``name``, ``description``, and ``Parameters`` (a
    pydantic model whose schema becomes the tool input schema).
    """

    name: str = ""
    description: str = ""
    Parameters: type[BaseModel]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    # Optional context injected by the registry on each call (user_id,
    # persona, history store, etc.).  Not part of the LLM-visible schema.
    def bind_context(self, **context: Any) -> None:
        for k, v in context.items():
            setattr(self, f"_ctx_{k}", v)

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Run the skill and return a text result for the LLM."""

    # ── Tool-format converters ─────────────────────────────────────────

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Convert to Anthropic tool-use format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": _clean_schema(self.Parameters.model_json_schema()),
        }

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _clean_schema(self.Parameters.model_json_schema()),
            },
        }

    def to_mcp_tool(self) -> dict[str, Any]:
        """Convert to MCP tools/list format (MCP 2024-11-05 spec)."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": _clean_schema(self.Parameters.model_json_schema()),
        }


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip pydantic metadata that LLM tool APIs reject (title, $defs)."""
    schema = dict(schema)
    schema.pop("title", None)
    if "properties" in schema:
        schema["properties"] = {
            k: {kk: vv for kk, vv in v.items() if kk != "title"}
            for k, v in schema["properties"].items()
        }
    return schema


class SkillRegistry:
    """In-process registry of skill instances.

    Owned by ``OpenOctoApp``; passed into the AI router so the tool-use
    loop can resolve tool names back to skill instances.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if not skill.name:
            raise ValueError(f"Skill {type(skill).__name__} has empty name")
        if skill.name in self._skills:
            raise ValueError(f"Skill {skill.name!r} already registered")
        self._skills[skill.name] = skill
        logger.info("Registered skill: %s", skill.name)

    def try_register(self, skill_cls: type[Skill], config: dict[str, Any] | None = None) -> Skill | None:
        """Attempt to instantiate and register a skill.

        Returns the instance on success, ``None`` if the skill raised
        ``SkillUnavailable`` (missing binary, unset config, etc.).
        """
        try:
            skill = skill_cls(config or {})
        except SkillUnavailable as e:
            logger.info("Skill %s unavailable: %s", skill_cls.__name__, e)
            return None
        except Exception:
            logger.exception("Skill %s failed to initialize", skill_cls.__name__)
            return None
        self.register(skill)
        return skill

    def unregister(self, name: str) -> None:
        """Remove a skill by name (no-op if not registered)."""
        if name in self._skills:
            del self._skills[name]
            logger.info("Unregistered skill: %s", name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return list(self._skills)

    def __len__(self) -> int:
        return len(self._skills)

    def __iter__(self):
        return iter(self._skills.values())

    def bind_context(self, **context: Any) -> None:
        for skill in self._skills.values():
            skill.bind_context(**context)

    # ── Tool-schema exports ────────────────────────────────────────────

    def anthropic_tools(self) -> list[dict[str, Any]]:
        return [s.to_anthropic_tool() for s in self._skills.values()]

    def openai_tools(self) -> list[dict[str, Any]]:
        return [s.to_openai_tool() for s in self._skills.values()]

    def mcp_tools(self) -> list[dict[str, Any]]:
        return [s.to_mcp_tool() for s in self._skills.values()]

    # ── Dispatch ───────────────────────────────────────────────────────

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Look up and run a skill, returning a string result.

        Errors are converted to a leading ``Error: ...`` line so the LLM
        can recover instead of crashing the pipeline.
        """
        skill = self._skills.get(name)
        if skill is None:
            return f"Error: unknown skill {name!r}"
        # External MCP tool skills set _skip_validation = True because their
        # inputSchema is passed through verbatim and has no pydantic Parameters.
        if getattr(skill, "_skip_validation", False):
            try:
                result = await skill.execute(**(arguments or {}))
            except SkillError as e:
                return f"Error: {e}"
            except Exception as e:
                logger.exception("Skill %s crashed", name)
                return f"Error: {name} failed: {e}"
            return result if isinstance(result, str) else str(result)
        try:
            validated = skill.Parameters(**(arguments or {}))
        except Exception as e:
            return f"Error: invalid arguments for {name}: {e}"
        try:
            result = await skill.execute(**validated.model_dump())
        except SkillError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Skill %s crashed", name)
            return f"Error: {name} failed: {e}"
        return result if isinstance(result, str) else str(result)
