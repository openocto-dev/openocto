"""Abstract base for AI backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable


class AIBackend(ABC):
    """Abstract AI backend."""

    @abstractmethod
    async def send(
        self,
        messages: list[dict],
        system_prompt: str,
    ) -> str:
        """Send messages and return a complete response.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."} dicts
            system_prompt: System prompt for this request

        Returns:
            Complete response text
        """

    @abstractmethod
    async def send_streaming(
        self,
        messages: list[dict],
        system_prompt: str,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        """Send messages and stream the response.

        Args:
            messages: Conversation messages
            system_prompt: System prompt
            on_chunk: Async callback called for each text chunk

        Returns:
            Complete response text (concatenated chunks)
        """
