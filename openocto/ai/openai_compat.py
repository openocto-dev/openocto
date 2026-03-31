"""OpenAI-compatible AI backend for any provider.

Works with OpenAI, Claude Max Proxy, Z.AI, Gemini, Alibaba Qwen,
DeepSeek, Ollama, or any provider implementing the OpenAI chat
completions API format.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Awaitable, Callable

import openai

from openocto.ai.base import AIBackend

if TYPE_CHECKING:
    from openocto.config import ProviderConfig

logger = logging.getLogger(__name__)


class OpenAICompatBackend(AIBackend):
    """AI backend for any OpenAI-compatible API."""

    def __init__(
        self,
        name: str,
        model: str,
        base_url: str,
        api_key: str = "",
        no_auth: bool = False,
    ) -> None:
        if not api_key and not no_auth:
            raise ValueError(
                f"API key for provider {name!r} is not set. "
                f"Set it in config or export the env var."
            )
        self._client = openai.AsyncOpenAI(
            api_key=api_key or "not-needed",
            base_url=base_url or None,
        )
        self._model = model
        self._name = name
        logger.info("%s backend initialized: %s (base_url=%s)", name, model, base_url)

    @classmethod
    def from_provider_config(cls, name: str, config: ProviderConfig) -> OpenAICompatBackend:
        return cls(
            name=name,
            model=config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            no_auth=config.no_auth,
        )

    async def send(self, messages: list[dict], system_prompt: str) -> str:
        all_messages = [{"role": "system", "content": system_prompt}, *messages]
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=all_messages,
        )
        text = response.choices[0].message.content or ""
        logger.debug("%s response (%d chars)", self._name, len(text))
        return text

    async def send_streaming(
        self,
        messages: list[dict],
        system_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        all_messages = [{"role": "system", "content": system_prompt}, *messages]
        full_text = []

        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=all_messages,
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                full_text.append(delta)
                await on_chunk(delta)

        return "".join(full_text)
