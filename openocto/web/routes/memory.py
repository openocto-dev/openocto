"""Memory routes — view facts, notes, and conversation summaries."""

from __future__ import annotations

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__

routes = web.RouteTableDef()


@routes.get("/memory")
@aiohttp_jinja2.template("memory.html")
async def memory_page(request: web.Request) -> dict:
    octo = request.app["octo"]
    hs = octo._history_store
    user_id = octo._current_user_id
    persona_name = octo._persona.name if octo._persona else "octo"

    facts = []
    notes = []
    summary = None

    if hs and user_id:
        facts = hs.get_active_facts(user_id)
        notes = hs.get_active_notes(user_id, persona_name)
        summary = hs.get_latest_summary(user_id, persona_name)

    flash = request.query.get("flash")
    flash_type = request.query.get("flash_type", "success")

    return {
        "page": "memory",
        "version": __version__,
        "facts": facts,
        "notes": notes,
        "summary": summary,
        "user_id": user_id,
        "persona": persona_name,
        "flash": flash,
        "flash_type": flash_type,
    }


@routes.post("/api/memory/facts")
async def add_fact(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    user_id = octo._current_user_id
    if not hs or not user_id:
        raise web.HTTPServiceUnavailable()

    data = await request.post()
    fact = data.get("fact", "").strip()
    category = data.get("category", "personal").strip()

    if not fact:
        raise web.HTTPFound("/memory?flash=Fact+text+is+required&flash_type=error")

    hs.add_fact(user_id, fact, category=category, source="manual")
    raise web.HTTPFound("/memory?flash=Fact+added")


@routes.post("/api/memory/facts/{fact_id}/delete")
async def delete_fact(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        raise web.HTTPServiceUnavailable()

    fact_id = int(request.match_info["fact_id"])
    hs.deactivate_fact(fact_id)
    raise web.HTTPFound("/memory?flash=Fact+removed")


@routes.post("/api/memory/notes/{note_id}/resolve")
async def resolve_note(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        raise web.HTTPServiceUnavailable()

    note_id = int(request.match_info["note_id"])
    hs.resolve_note(note_id)
    raise web.HTTPFound("/memory?flash=Note+resolved")
