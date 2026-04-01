"""Tests for the AI Router with mocked backends."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openocto.ai.router import AIRouter
from openocto.config import AIConfig, ClaudeConfig


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
    async def test_send_passes_history_and_text(self, config_with_claude):
        mock_backend = AsyncMock()
        mock_backend.send.return_value = "Hello, I am a test response."
        router, _ = make_router(config_with_claude, mock_backend)

        history = [{"role": "user", "content": "prev"}, {"role": "assistant", "content": "prev-resp"}]
        response = await router.send("Hello", history, "You are a test assistant.")

        assert response == "Hello, I am a test response."
        # Backend should receive history + current message
        sent_messages = mock_backend.send.call_args[0][0]
        assert len(sent_messages) == 3
        assert sent_messages[-1] == {"role": "user", "content": "Hello"}

    @pytest.mark.asyncio
    async def test_send_passes_system_prompt(self, config_with_claude):
        mock_backend = AsyncMock()
        mock_backend.send.return_value = "response"
        router, _ = make_router(config_with_claude, mock_backend)

        await router.send("test", [], "You are a test assistant.")

        call_kwargs = mock_backend.send.call_args
        assert call_kwargs[0][1] == "You are a test assistant."

    @pytest.mark.asyncio
    async def test_send_with_empty_history(self, config_with_claude):
        mock_backend = AsyncMock()
        mock_backend.send.return_value = "hi"
        router, _ = make_router(config_with_claude, mock_backend)

        response = await router.send("Hello", [], "You are a test assistant.")
        assert response == "hi"
        sent_messages = mock_backend.send.call_args[0][0]
        assert len(sent_messages) == 1
        assert sent_messages[0] == {"role": "user", "content": "Hello"}

    @pytest.mark.asyncio
    async def test_send_streaming(self, config_with_claude):
        mock_backend = AsyncMock()
        mock_backend.send_streaming.return_value = "Streamed response."
        router, _ = make_router(config_with_claude, mock_backend)

        async def noop(chunk: str) -> None:
            pass

        history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        response = await router.send_streaming("Hi", history, "You are a test assistant.", on_chunk=noop)
        assert response == "Streamed response."
        sent_messages = mock_backend.send_streaming.call_args[0][0]
        assert len(sent_messages) == 3

    def test_get_backend_returns_correct(self, config_with_claude):
        router, mock = make_router(config_with_claude)
        assert router.get_backend("claude") is mock

    def test_get_backend_unknown_raises(self, config_with_claude):
        router, _ = make_router(config_with_claude)
        with pytest.raises(ValueError):
            router.get_backend("nonexistent")
