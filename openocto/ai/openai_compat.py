"""OpenAI-compatible AI backend for any provider.

Works with OpenAI, Claude Max Proxy, Z.AI, Gemini, Alibaba Qwen,
DeepSeek, Ollama, or any provider implementing the OpenAI chat
completions API format.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import openai

from openocto.ai.base import AIBackend

if TYPE_CHECKING:
    from openocto.config import ProviderConfig
    from openocto.skills.base import SkillRegistry

logger = logging.getLogger(__name__)

_MAX_TOOL_ITERATIONS = 6


class OpenAICompatBackend(AIBackend):
    """AI backend for any OpenAI-compatible API."""

    supports_tools = True

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

    async def send(
        self,
        messages: list[dict],
        system_prompt: str,
        skills: SkillRegistry | None = None,
    ) -> str:
        all_messages = [{"role": "system", "content": system_prompt}, *messages]

        if skills and len(skills) > 0:
            return await self._tool_loop(all_messages, skills)

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
        skills: SkillRegistry | None = None,
    ) -> str:
        all_messages = [{"role": "system", "content": system_prompt}, *messages]

        if skills and len(skills) > 0:
            return await self._tool_loop(all_messages, skills, on_chunk=on_chunk)

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

    # ── Tool-use loop ──────────────────────────────────────────────────

    async def _tool_loop(
        self,
        messages: list[dict[str, Any]],
        skills: SkillRegistry,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Run an OpenAI function-calling loop until a final assistant text.

        On each iteration we send the running conversation with ``tools``;
        if the model returns ``tool_calls``, we execute each, append a
        ``tool`` message with the result, and loop.
        """
        convo: list[dict[str, Any]] = list(messages)
        tools = skills.openai_tools()

        for _ in range(_MAX_TOOL_ITERATIONS):
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=convo,
                tools=tools,
            )
            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls:
                text = msg.content or ""
                if on_chunk and text:
                    await on_chunk(text)
                return text

            # Persist the assistant tool-call turn.
            convo.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                logger.info("Tool call: %s(%s)", tc.function.name, args)
                result = await skills.call(tc.function.name, args)
                convo.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        logger.warning("Tool loop hit max iterations (%d)", _MAX_TOOL_ITERATIONS)
        return "Sorry, I got stuck in a tool loop."
