"""Tests for the AI Router with mocked backends."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openocto.ai.router import AIRouter
from openocto.config import AIConfig, ClaudeConfig
from openocto.persona.manager import Persona


@pytest.fixture
def mock_persona() -> Persona:
    return Persona(
        name="test",
        display_name="Test",
        description="",
        system_prompt="You are a test assistant.",
    )


@pytest.fixture
def config_with_claude() -> AIConfig:
    return AIConfig(
        default_backend="claude",
        claude=ClaudeConfig(api_key="test-key", model="claude-test"),
    )


# Patch the import inside _init_backends
CLAUDE_PATCH = "openocto.ai.claude.ClaudeBackend"
ROUTER_CLAUDE_PATCH = "openocto.ai.router.ClaudeBackend"


def make_router(config: AIConfig, mock_backend=None):
    """Create AIRouter with a mocked Claude backend."""
    mock = mock_backend or MagicMock()
    with patch("openocto.ai.claude.anthropic"):
        # Patch the class inside the router's local import
        original_init = AIRouter._init_backends

        def patched_init(self):
            self._backends["claude"] = mock
            self._active_backend_name = "claude"

        with patch.object(AIRouter, "_init_backends", patched_init):
            router = AIRouter(config)
    return router, mock


class TestAIRouter:
    def test_init_with_valid_backend(self, config_with_claude):
        router, mock = make_router(config_with_claude)
        assert router.active_backend_name == "claude"

    def test_init_no_api_keys_raises(self):
        config = AIConfig(default_backend="claude")
        with pytest.raises(RuntimeError, match="No AI backends available"):
            AIRouter(config)

    def test_set_backend(self, config_with_claude):
        router, _ = make_router(config_with_claude)
        router.set_backend("claude")
        assert router.active_backend_name == "claude"

    def test_set_unknown_backend_raises(self, config_with_claude):
        router, _ = make_router(config_with_claude)
        with pytest.raises(ValueError, match="not available"):
            router.set_backend("unknown_backend")

    @pytest.mark.asyncio
    async def test_send_adds_to_history(self, config_with_claude, mock_persona):
        mock_backend = AsyncMock()
        mock_backend.send.return_value = "Hello, I am a test response."
        router, _ = make_router(config_with_claude, mock_backend)

        response = await router.send("Hello", mock_persona)

        assert response == "Hello, I am a test response."
        assert len(router._history) == 2
        assert router._history[0] == {"role": "user", "content": "Hello"}
        assert router._history[1] == {"role": "assistant", "content": "Hello, I am a test response."}

    @pytest.mark.asyncio
    async def test_send_passes_system_prompt(self, config_with_claude, mock_persona):
        mock_backend = AsyncMock()
        mock_backend.send.return_value = "response"
        router, _ = make_router(config_with_claude, mock_backend)

        await router.send("test", mock_persona)

        call_kwargs = mock_backend.send.call_args
        assert call_kwargs[0][1] == mock_persona.system_prompt

    @pytest.mark.asyncio
    async def test_send_streaming_calls_backend(self, config_with_claude, mock_persona):
        mock_backend = AsyncMock()
        mock_backend.send_streaming.return_value = "Streamed response."
        router, _ = make_router(config_with_claude, mock_backend)

        async def noop(chunk: str) -> None:
            pass

        response = await router.send_streaming("Hi", mock_persona, on_chunk=noop)
        assert response == "Streamed response."
        assert router._history[-1] == {"role": "assistant", "content": "Streamed response."}

    def test_clear_history(self, config_with_claude):
        router, _ = make_router(config_with_claude)
        router._history = [{"role": "user", "content": "test"}]
        router.clear_history()
        assert router._history == []

    def test_history_trimmed_when_too_long(self, config_with_claude):
        config_with_claude.max_history = 2
        router, _ = make_router(config_with_claude)
        for i in range(10):
            router._history.append({"role": "user", "content": f"msg {i}"})
            router._history.append({"role": "assistant", "content": f"resp {i}"})
        router._trim_history()
        assert len(router._history) == 4  # max_history=2 turns = 4 messages

    def test_get_backend_returns_correct(self, config_with_claude):
        router, mock = make_router(config_with_claude)
        assert router.get_backend("claude") is mock

    def test_get_backend_unknown_raises(self, config_with_claude):
        router, _ = make_router(config_with_claude)
        with pytest.raises(ValueError):
            router.get_backend("nonexistent")
