"""Dashboard route — main page with pipeline state overview."""

from __future__ import annotations

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__

routes = web.RouteTableDef()


@routes.get("/")
@aiohttp_jinja2.template("dashboard.html")
async def dashboard(request: web.Request) -> dict:
    octo = request.app["octo"]

    state = "idle"
    if octo._state_machine:
        state = octo._state_machine.state.value

    user_name = None
    if octo._current_user_id and octo._history_store:
        users = octo._history_store.list_users()
        for u in users:
            if u["id"] == octo._current_user_id:
                user_name = u["name"]
                break

    persona_name = None
    if octo._persona:
        persona_name = octo._persona.display_name

    backend = octo._config.ai.default_backend

    return {
        "page": "dashboard",
        "version": __version__,
        "state": state,
        "user_name": user_name or "Not set",
        "persona_name": persona_name or "Not set",
        "backend": backend,
        "web_port": octo._config.web.port,
    }
