"""Tests for the JSON API v1 namespace.

Covers auth, status, users, personas, messages, and memory endpoints.
The web app is built directly here (no full OpenOctoApp) — same pattern
as the existing test_web.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from openocto.web.api_auth import get_or_create_api_token
from openocto.web.routes.api_v1 import routes as api_v1_routes


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_history_store():
    hs = MagicMock()
    hs.list_users.return_value = [
        {"id": 1, "name": "Alice", "is_default": True},
        {"id": 2, "name": "Bob", "is_default": False},
    ]
    hs.get_user_by_name.return_value = None
    hs.create_user.return_value = 3
    hs.set_default_user.return_value = None
    hs.delete_user.return_value = None
    hs.add_message.side_effect = [101, 102]  # user_msg_id, assistant_msg_id
    hs.get_recent_messages.return_value = [
        {"id": 99, "role": "user", "content": "hi", "created_at": "2026-04-13 10:00:00"},
    ]
    hs.get_messages_after.return_value = [
        {"id": 100, "role": "assistant", "content": "hello", "created_at": "2026-04-13 10:00:01"},
    ]
    hs.clear_history.return_value = 5
    hs.get_active_facts.return_value = [{"id": 1, "category": "general", "text": "Likes coffee"}]
    hs.add_fact.return_value = 42
    hs.deactivate_fact.return_value = None
    hs.get_active_notes.return_value = [{"id": 1, "text": "buy milk"}]
    hs.resolve_note.return_value = None
    return hs


def _make_persona():
    p = SimpleNamespace(
        name="octo",
        display_name="Octo",
        system_prompt="You are Octo.",
    )
    return p


def _make_persona_manager():
    pm = MagicMock()
    pm.list_personas.return_value = [
        {"name": "octo", "display_name": "Octo"},
        {"name": "hestia", "display_name": "Hestia"},
    ]
    pm.activate.side_effect = lambda name: (
        SimpleNamespace(name=name, system_prompt="...")
        if name in ("octo", "hestia")
        else (_ for _ in ()).throw(ValueError(name))
    )
    return pm


def _make_octo():
    return SimpleNamespace(
        _config=SimpleNamespace(),
        _history_store=_make_history_store(),
        _persona=_make_persona(),
        _persona_manager=_make_persona_manager(),
        _current_user_id=1,
        _ai_router=None,
        _skills=None,
        _player=None,
    )


def _make_app(octo=None):
    octo = octo or _make_octo()
    app = web.Application()
    app["octo"] = octo
    app.router.add_routes(api_v1_routes)
    return app, octo


@pytest.fixture
def auth_headers():
    token = get_or_create_api_token()
    return {"Authorization": f"Bearer {token}"}


# ── Auth ──────────────────────────────────────────────────────────────────────


class TestAuth:
    async def test_missing_token_returns_401(self, aiohttp_client):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/status")
        assert resp.status == 401
        body = await resp.json()
        assert body["error"] == "unauthorized"

    async def test_wrong_token_returns_401(self, aiohttp_client):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.get(
            "/api/v1/status",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status == 401

    async def test_valid_token_succeeds(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/status", headers=auth_headers)
        assert resp.status == 200

    async def test_bearer_scheme_case_insensitive(self, aiohttp_client):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        token = get_or_create_api_token()
        resp = await client.get(
            "/api/v1/status",
            headers={"Authorization": f"bearer {token}"},
        )
        assert resp.status == 200


# ── Status ────────────────────────────────────────────────────────────────────


class TestStatus:
    async def test_status_shape(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/status", headers=auth_headers)
        assert resp.status == 200
        data = await resp.json()
        assert "version" in data
        assert "active_user_id" in data
        assert "active_persona" in data
        assert data["active_persona"] == "octo"
        assert data["active_user_id"] == 1


# ── Users ─────────────────────────────────────────────────────────────────────


class TestUsers:
    async def test_list_users(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/users", headers=auth_headers)
        assert resp.status == 200
        data = await resp.json()
        assert len(data["users"]) == 2
        assert data["active_user_id"] == 1

    async def test_create_user(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.post(
            "/api/v1/users", headers=auth_headers, json={"name": "Carol"},
        )
        assert resp.status == 201
        data = await resp.json()
        assert data["id"] == 3
        assert data["name"] == "Carol"

    async def test_create_user_requires_name(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.post("/api/v1/users", headers=auth_headers, json={})
        assert resp.status == 400

    async def test_create_user_duplicate(self, aiohttp_client, auth_headers):
        app, octo = _make_app()
        octo._history_store.get_user_by_name.return_value = {"id": 1, "name": "Alice"}
        client = await aiohttp_client(app)
        resp = await client.post(
            "/api/v1/users", headers=auth_headers, json={"name": "Alice"},
        )
        assert resp.status == 400

    async def test_activate_user(self, aiohttp_client, auth_headers):
        app, octo = _make_app()
        client = await aiohttp_client(app)
        resp = await client.post("/api/v1/users/2/activate", headers=auth_headers)
        assert resp.status == 200
        data = await resp.json()
        assert data["active_user_id"] == 2
        assert octo._current_user_id == 2

    async def test_activate_unknown_user(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.post("/api/v1/users/999/activate", headers=auth_headers)
        assert resp.status == 404

    async def test_set_default(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.post("/api/v1/users/2/default", headers=auth_headers)
        assert resp.status == 200

    async def test_delete_user(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.delete("/api/v1/users/2", headers=auth_headers)
        assert resp.status == 200

    async def test_cannot_delete_active_user(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.delete("/api/v1/users/1", headers=auth_headers)
        assert resp.status == 400


# ── Personas ──────────────────────────────────────────────────────────────────


class TestPersonas:
    async def test_list_personas(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/personas", headers=auth_headers)
        assert resp.status == 200
        data = await resp.json()
        assert len(data["personas"]) == 2
        assert data["active_persona"] == "octo"

    async def test_activate_persona(self, aiohttp_client, auth_headers):
        app, octo = _make_app()
        client = await aiohttp_client(app)
        resp = await client.post("/api/v1/personas/hestia/activate", headers=auth_headers)
        assert resp.status == 200
        data = await resp.json()
        assert data["active_persona"] == "hestia"
        assert octo._persona.name == "hestia"

    async def test_activate_unknown_persona(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.post("/api/v1/personas/nonexistent/activate", headers=auth_headers)
        assert resp.status == 404


# ── Messages ──────────────────────────────────────────────────────────────────


class TestMessages:
    async def test_list_recent(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/messages", headers=auth_headers)
        assert resp.status == 200
        data = await resp.json()
        assert "messages" in data
        assert data["user_id"] == 1

    async def test_list_after_id(self, aiohttp_client, auth_headers):
        app, octo = _make_app()
        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/messages?after_id=50", headers=auth_headers)
        assert resp.status == 200
        # get_messages_after should be called, not get_recent_messages
        octo._history_store.get_messages_after.assert_called_once()

    async def test_send_message(self, aiohttp_client, auth_headers):
        app, octo = _make_app()
        ai_router = MagicMock()
        ai_router.send = AsyncMock(return_value="hello back")
        octo._ai_router = ai_router

        client = await aiohttp_client(app)
        resp = await client.post(
            "/api/v1/messages", headers=auth_headers, json={"content": "hi"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["content"] == "hello back"
        assert data["user_msg_id"] == 101
        assert data["assistant_msg_id"] == 102

    async def test_send_empty_content(self, aiohttp_client, auth_headers):
        app, octo = _make_app()
        octo._ai_router = MagicMock()
        client = await aiohttp_client(app)
        resp = await client.post(
            "/api/v1/messages", headers=auth_headers, json={"content": ""},
        )
        assert resp.status == 400

    async def test_send_no_ai_router(self, aiohttp_client, auth_headers):
        app, _ = _make_app()  # _ai_router is None
        client = await aiohttp_client(app)
        resp = await client.post(
            "/api/v1/messages", headers=auth_headers, json={"content": "hi"},
        )
        assert resp.status == 503

    async def test_clear_messages(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.delete("/api/v1/messages", headers=auth_headers)
        assert resp.status == 200
        data = await resp.json()
        assert data["deleted"] == 5


# ── Memory ────────────────────────────────────────────────────────────────────


class TestMemory:
    async def test_list_facts(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/memory/facts", headers=auth_headers)
        assert resp.status == 200
        data = await resp.json()
        assert len(data["facts"]) == 1

    async def test_add_fact(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.post(
            "/api/v1/memory/facts", headers=auth_headers,
            json={"text": "Likes tea", "category": "preferences"},
        )
        assert resp.status == 201
        data = await resp.json()
        assert data["id"] == 42

    async def test_add_fact_requires_text(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.post(
            "/api/v1/memory/facts", headers=auth_headers, json={},
        )
        assert resp.status == 400

    async def test_delete_fact(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.delete("/api/v1/memory/facts/42", headers=auth_headers)
        assert resp.status == 200

    async def test_list_notes(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/memory/notes", headers=auth_headers)
        assert resp.status == 200

    async def test_resolve_note(self, aiohttp_client, auth_headers):
        app, _ = _make_app()
        client = await aiohttp_client(app)
        resp = await client.post(
            "/api/v1/memory/notes/1/resolve", headers=auth_headers,
        )
        assert resp.status == 200
