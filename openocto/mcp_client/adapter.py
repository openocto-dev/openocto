"""MCPRemoteToolSkill — wraps a single external MCP tool as a Skill.

Each tool from a connected MCP server becomes an ``MCPRemoteToolSkill``
that is registered in the shared ``SkillRegistry`` under the prefixed name
``<server_name>__<tool_name>`` (double-underscore separator).

The class sets ``_skip_validation = True`` so the registry dispatcher
bypasses pydantic validation and calls :meth:`execute` directly with the
raw kwargs.  The ``inputSchema`` from the MCP server is passed through
verbatim to the LLM — no pydantic re-encoding that would lose anyOf/$ref.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel

from openocto.skills.base import Skill, SkillError
from openocto.mcp_client.client import MCPClient, MCPClientError

logger = logging.getLogger(__name__)

# Anthropic tool name limit
_MAX_NAME_LEN = 64


def _sanitize_name(raw: str) -> str:
    """Sanitize a raw ``<server>__<tool>`` name for use as a skill name.

    Rules:
    * Lowercase everything
    * Replace any character outside ``[a-z0-9_]`` with ``_``
    * Collapse consecutive underscores — BUT preserve exactly two underscores
      where the original had ``__`` (the server/tool separator)
    * Strip leading/trailing underscores
    * Truncate to 64 characters
    """
    name = raw.lower()
    # Temporarily protect the double-underscore separator
    name = name.replace("__", "\x00")
    name = re.sub(r"[^a-z0-9_\x00]", "_", name)
    # Restore separator before collapsing single underscores
    name = re.sub(r"_+", "_", name)
    name = name.replace("\x00", "__")
    name = name.strip("_")
    return name[:_MAX_NAME_LEN]


class _EmptyParams(BaseModel):
    """Dummy pydantic model used so the Skill ABC does not complain."""


class MCPRemoteToolSkill(Skill):
    """A skill that proxies one tool from an external MCP server.

    The ``_skip_validation`` class attribute tells :class:`SkillRegistry`
    to bypass pydantic argument parsing and call :meth:`execute` directly.
    """

    _skip_validation = True
    Parameters = _EmptyParams

    def __init__(
        self,
        client: MCPClient,
        tool_def: dict[str, Any],
        server_name: str,
    ) -> None:
        super().__init__()
        self._client = client
        self._server_name = server_name
        self._raw_tool_name: str = tool_def["name"]
        self._input_schema: dict[str, Any] = tool_def.get(
            "inputSchema", {"type": "object", "properties": {}}
        )

        # Prefixed, sanitized name
        self.name = _sanitize_name(f"{server_name}__{self._raw_tool_name}")
        raw_desc = tool_def.get("description") or ""
        self.description = f"[{server_name}] {raw_desc}".strip()

    # ── Tool-format overrides — pass inputSchema verbatim ────────────────

    def to_anthropic_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._input_schema,
        }

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._input_schema,
            },
        }

    def to_mcp_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self._input_schema,
        }

    # ── Execution ─────────────────────────────────────────────────────────

    async def execute(self, **kwargs: Any) -> str:
        """Forward the call to the remote MCP server and extract text content."""
        try:
            result = await self._client.call_tool(self._raw_tool_name, kwargs)
        except MCPClientError as exc:
            self._client.unhealthy = True
            raise SkillError(
                f"MCP server {self._server_name!r} failed: {exc}"
            ) from exc

        # Extract text from content array
        is_error = result.get("isError", False)
        content = result.get("content", [])
        texts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        text = "\n".join(t for t in texts if t)

        if is_error:
            return f"Error: {text}" if text else "Error: MCP tool returned an error"
        return text if text else "(no output)"
