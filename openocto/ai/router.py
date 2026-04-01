"""AI Backend Router — selects and manages AI backends."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Awaitable, Callable

from openocto.ai.base import AIBackend

if TYPE_CHECKING:
    from openocto.config import AIConfig

logger = logging.getLogger(__name__)


class AIRouter:
    """Routes requests to the configured AI backend."""

    def __init__(self, config: AIConfig) -> None:
        self._config = config
        self._backends: dict[str, AIBackend] = {}
        self._active_backend_name = config.default_backend

        self._init_backends()

    def _init_backends(self) -> None:
        """Initialize all configured backends."""
        from openocto.ai.claude import ClaudeBackend
        from openocto.ai.openai_compat import OpenAICompatBackend

        errors = []

        # Native Anthropic API (uses anthropic SDK)
        if self._config.claude.api_key:
            try:
                self._backends["claude"] = ClaudeBackend(self._config.claude)
            except Exception as e:
                errors.append(f"claude: {e}")

        # OpenAI-compatible providers (any number)
        for name, provider_config in self._config.providers.items():
            if not provider_config.model:
                continue  # skip unconfigured providers
            if not provider_config.api_key and not provider_config.no_auth:
                continue  # skip providers without auth
            try:
                self._backends[name] = OpenAICompatBackend.from_provider_config(
                    name, provider_config
                )
            except Exception as e:
                errors.append(f"{name}: {e}")

        if errors:
            logger.warning("Some backends failed to initialize: %s", "; ".join(errors))

        if not self._backends:
            raise RuntimeError(
                "No AI backends available. Set at least one API key:\n"
                "  export ANTHROPIC_API_KEY=sk-...       (for Claude API)\n"
                "  export OPENAI_API_KEY=sk-...           (for OpenAI)\n"
                "Or use claude-proxy with your Claude subscription:\n"
                "  openocto start --ai claude-proxy"
            )

        if self._active_backend_name not in self._backends:
            fallback = next(iter(self._backends))
            logger.warning(
                "Requested backend %r not available, using %r",
                self._active_backend_name,
                fallback,
            )
            self._active_backend_name = fallback

    def get_backend(self, name: str | None = None) -> AIBackend:
        backend_name = name or self._active_backend_name
        if backend_name not in self._backends:
            raise ValueError(f"Backend {backend_name!r} not available")
        return self._backends[backend_name]

    @property
    def active_backend_name(self) -> str:
        return self._active_backend_name

    def set_backend(self, name: str) -> None:
        if name not in self._backends:
            raise ValueError(f"Backend {name!r} not available. Available: {list(self._backends)}")
        self._active_backend_name = name
        logger.info("Switched to backend: %s", name)

    async def send(
        self,
        user_text: str,
        history: list[dict],
        system_prompt: str,
    ) -> str:
        """Send a user message and get a complete response.

        Args:
            user_text: the current user message.
            history: previous messages (caller loads from DB).
            system_prompt: assembled system prompt (persona + memory context).
        """
        messages = [*history, {"role": "user", "content": user_text}]
        backend = self.get_backend()
        return await backend.send(messages, system_prompt)

    async def send_streaming(
        self,
        user_text: str,
        history: list[dict],
        system_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        """Send a user message and stream the response.

        Args:
            user_text: the current user message.
            history: previous messages (caller loads from DB).
            system_prompt: assembled system prompt (persona + memory context).
            on_chunk: callback for each streamed token.
        """
        messages = [*history, {"role": "user", "content": user_text}]
        backend = self.get_backend()
        return await backend.send_streaming(messages, system_prompt, on_chunk)
