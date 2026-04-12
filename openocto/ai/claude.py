"""Claude AI backend using the Anthropic SDK."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import anthropic

from openocto.ai.base import AIBackend

if TYPE_CHECKING:
    from openocto.config import ClaudeConfig
    from openocto.skills.base import SkillRegistry

logger = logging.getLogger(__name__)

_MAX_TOOL_ITERATIONS = 6  # safety bound on the tool-use loop


class ClaudeBackend(AIBackend):
    """AI backend using Anthropic's Claude API."""

    supports_tools = True

    def __init__(self, config: ClaudeConfig) -> None:
        if not config.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it: export ANTHROPIC_API_KEY=sk-..."
            )
        self._client = anthropic.AsyncAnthropic(api_key=config.api_key)
        self._model = config.model
        logger.info("Claude backend initialized: %s", self._model)

    async def send(
        self,
        messages: list[dict],
        system_prompt: str,
        skills: SkillRegistry | None = None,
    ) -> str:
        if skills and len(skills) > 0:
            return await self._tool_loop(messages, system_prompt, skills)

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        text = _extract_text(response.content)
        logger.debug("Claude response (%d chars)", len(text))
        return text

    async def send_streaming(
        self,
        messages: list[dict],
        system_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
        skills: SkillRegistry | None = None,
    ) -> str:
        if skills and len(skills) > 0:
            # Tool-use loop runs all but the final round non-streaming;
            # the final assistant message is streamed for low TTFT.
            return await self._tool_loop(
                messages, system_prompt, skills, on_chunk=on_chunk,
            )

        full_text = []
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for chunk in stream.text_stream:
                full_text.append(chunk)
                await on_chunk(chunk)

        return "".join(full_text)

    # ── Tool-use loop ──────────────────────────────────────────────────

    async def _tool_loop(
        self,
        messages: list[dict],
        system_prompt: str,
        skills: SkillRegistry,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Run an Anthropic tool-use loop until a final text answer.

        Each iteration we send the running conversation; if the model
        returns ``stop_reason=tool_use``, we execute the requested tool
        via the registry, append the tool result, and loop again.
        """
        # Local copy — we mutate it across iterations.
        convo: list[dict[str, Any]] = list(messages)
        tools = skills.anthropic_tools()

        for _ in range(_MAX_TOOL_ITERATIONS):
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=system_prompt,
                tools=tools,
                messages=convo,
            )

            if response.stop_reason != "tool_use":
                # Final answer — replay text via on_chunk if streaming.
                text = _extract_text(response.content)
                if on_chunk and text:
                    await on_chunk(text)
                return text

            # Persist the assistant's tool_use turn into the conversation
            # exactly as the API returned it.
            convo.append({"role": "assistant", "content": _serialize_blocks(response.content)})

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                logger.info("Tool call: %s(%s)", block.name, block.input)
                result = await skills.call(block.name, block.input or {})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            convo.append({"role": "user", "content": tool_results})

        logger.warning("Tool loop hit max iterations (%d)", _MAX_TOOL_ITERATIONS)
        return "Sorry, I got stuck in a tool loop."


def _extract_text(content_blocks: list[Any]) -> str:
    """Concatenate all text blocks from an Anthropic response."""
    parts = []
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


def _serialize_blocks(content_blocks: list[Any]) -> list[dict[str, Any]]:
    """Convert SDK content blocks to plain dicts for round-trip in messages."""
    out: list[dict[str, Any]] = []
    for block in content_blocks:
        btype = getattr(block, "type", None)
        if btype == "text":
            out.append({"type": "text", "text": block.text})
        elif btype == "tool_use":
            out.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return out
