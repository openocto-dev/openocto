"""Claude AI backend using the Anthropic SDK."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Awaitable, Callable

import anthropic

from openocto.ai.base import AIBackend

if TYPE_CHECKING:
    from openocto.config import ClaudeConfig

logger = logging.getLogger(__name__)


class ClaudeBackend(AIBackend):
    """AI backend using Anthropic's Claude API."""

    def __init__(self, config: ClaudeConfig) -> None:
        if not config.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it: export ANTHROPIC_API_KEY=sk-..."
            )
        self._client = anthropic.AsyncAnthropic(api_key=config.api_key)
        self._model = config.model
        logger.info("Claude backend initialized: %s", self._model)

    async def send(self, messages: list[dict], system_prompt: str) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        text = response.content[0].text
        logger.debug("Claude response (%d chars)", len(text))
        return text

    async def send_streaming(
        self,
        messages: list[dict],
        system_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
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
