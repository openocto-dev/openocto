"""Tests for the web admin module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from openocto.config import AppConfig


def _make_mock_octo_app() -> MagicMock:
    """Create a mock OpenOctoApp with all required attributes."""
    from openocto.event_bus import EventBus
    from openocto.state_machine import State

    mock = MagicMock()
    mock._config = AppConfig()
    mock._event_bus = EventBus()
    mock._state_machine = MagicMock()
    mock._state_machine.state = State.IDLE
    mock._history_store = MagicMock()
    mock._history_store.list_users.return_value = [
        {"id": 1, "name": "TestUser", "is_default": True}
    ]
    mock._current_user_id = 1
    mock._persona = MagicMock()
    mock._persona.display_name = "Octo"
    mock._memory = None
    mock._ai_router = MagicMock()
    return mock


@pytest.fixture
def octo_app():
    return _make_mock_octo_app()


@pytest.fixture
def web_app(octo_app):
    from openocto.web.server import create_web_app
    return create_web_app(octo_app)


class TestWebConfig:
    def test_web_config_defaults(self):
        from openocto.config import WebConfig
        c = WebConfig()
        assert c.enabled is True
        assert c.host == "0.0.0.0"
        assert c.port == 8080

    def test_app_config_has_web(self):
        config = AppConfig()
        assert hasattr(config, "web")
        assert config.web.enabled is True
        assert config.web.port == 8080


class TestFirstRunRedirect:
    @pytest.mark.asyncio
    async def test_redirects_when_no_config(self, web_app, aiohttp_client):
        with patch("openocto.web.server.USER_CONFIG_PATH", Path("/nonexistent/config.yaml")):
            # Need to recreate the app with the patched path
            from openocto.web.server import create_web_app
            app = create_web_app(web_app["octo"])
            client = await aiohttp_client(app)
            resp = await client.get("/", allow_redirects=False)
            assert resp.status == 302
            assert resp.headers["Location"] == "/wizard"

    @pytest.mark.asyncio
    async def test_no_redirect_when_config_exists(self, web_app, aiohttp_client, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("persona: octo\n")
        with patch("openocto.web.server.USER_CONFIG_PATH", config_path):
            from openocto.web.server import create_web_app
            app = create_web_app(web_app["octo"])
            client = await aiohttp_client(app)
            resp = await client.get("/")
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_wizard_accessible_without_config(self, web_app, aiohttp_client):
        with patch("openocto.web.server.USER_CONFIG_PATH", Path("/nonexistent/config.yaml")):
            from openocto.web.server import create_web_app
            app = create_web_app(web_app["octo"])
            client = await aiohttp_client(app)
            resp = await client.get("/wizard")
            assert resp.status == 200


class TestDashboard:
    @pytest.mark.asyncio
    async def test_dashboard_renders(self, web_app, aiohttp_client, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("persona: octo\n")
        with patch("openocto.web.server.USER_CONFIG_PATH", config_path):
            from openocto.web.server import create_web_app
            app = create_web_app(web_app["octo"])
            client = await aiohttp_client(app)
            resp = await client.get("/")
            assert resp.status == 200
            text = await resp.text()
            assert "Dashboard" in text
            assert "idle" in text
            assert "Octo" in text


class TestWizard:
    @pytest.mark.asyncio
    async def test_wizard_renders(self, web_app, aiohttp_client):
        with patch("openocto.web.server.USER_CONFIG_PATH", Path("/nonexistent")):
            from openocto.web.server import create_web_app
            app = create_web_app(web_app["octo"])
            client = await aiohttp_client(app)
            resp = await client.get("/wizard")
            assert resp.status == 200
            text = await resp.text()
            assert "Welcome to OpenOcto" in text
            assert "AI Backend" in text

    @pytest.mark.asyncio
    async def test_wizard_save(self, web_app, aiohttp_client, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_dir = tmp_path

        with (
            patch("openocto.web.server.USER_CONFIG_PATH", Path("/nonexistent")),
            patch("openocto.web.routes.wizard.save_wizard_config") as mock_save,
            patch("openocto.web.routes.wizard.HistoryStore") as mock_store_cls,
        ):
            mock_save.return_value = config_path
            mock_store = MagicMock()
            mock_store.get_user_by_name.return_value = None
            mock_store_cls.return_value = mock_store

            from openocto.web.server import create_web_app
            app = create_web_app(web_app["octo"])
            client = await aiohttp_client(app)

            resp = await client.post("/api/wizard/save", json={
                "user_name": "TestUser",
                "backend": "ollama",
                "ollama_model": "qwen3:4b",
                "model_size": "small",
                "primary_lang": "auto",
            })
            assert resp.status == 200
            data = await resp.json()
            assert data["ok"] is True

            mock_store.create_user.assert_called_once_with("TestUser", is_default=True)
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_ollama_models_api(self, web_app, aiohttp_client):
        with (
            patch("openocto.web.server.USER_CONFIG_PATH", Path("/nonexistent")),
            patch("openocto.web.routes.wizard.is_ollama_installed", return_value=True),
            patch("openocto.web.routes.wizard.list_ollama_models", return_value=["llama3:latest", "qwen3:4b"]),
        ):
            from openocto.web.server import create_web_app
            app = create_web_app(web_app["octo"])
            client = await aiohttp_client(app)

            resp = await client.get("/api/wizard/ollama-models")
            assert resp.status == 200
            data = await resp.json()
            assert data["installed"] is True
            assert "llama3:latest" in data["models"]
            assert "qwen3:4b" in data["models"]


class TestWebSocket:
    @pytest.mark.asyncio
    async def test_ws_connects_and_receives_state(self, web_app, aiohttp_client, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("persona: octo\n")
        with patch("openocto.web.server.USER_CONFIG_PATH", config_path):
            from openocto.web.server import create_web_app
            app = create_web_app(web_app["octo"])
            client = await aiohttp_client(app)

            async with client.ws_connect("/ws") as ws:
                msg = await ws.receive_json()
                assert msg["type"] == "state"
                assert msg["data"]["state"] == "idle"
