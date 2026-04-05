"""Persona routes — list personas, view/edit system prompts."""

from __future__ import annotations

from pathlib import Path

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__

routes = web.RouteTableDef()


@routes.get("/personas")
@aiohttp_jinja2.template("personas.html")
async def personas_page(request: web.Request) -> dict:
    octo = request.app["octo"]

    personas = []
    if octo._persona_manager:
        for p in octo._persona_manager.list_personas():
            personas.append({
                "name": p["name"],
                "display_name": p["display_name"],
                "description": p.get("description", ""),
                "is_active": octo._persona and p["name"] == octo._persona.name,
            })

    flash = request.query.get("flash")
    flash_type = request.query.get("flash_type", "success")

    return {
        "page": "personas",
        "version": __version__,
        "personas": personas,
        "flash": flash,
        "flash_type": flash_type,
    }


@routes.get("/personas/{name}")
@aiohttp_jinja2.template("persona_edit.html")
async def persona_edit_page(request: web.Request) -> dict:
    octo = request.app["octo"]
    name = request.match_info["name"]

    persona = None
    system_prompt = ""

    if octo._persona_manager:
        for p in octo._persona_manager.list_personas():
            if p["name"] == name:
                persona = p
                break

    if persona is None:
        raise web.HTTPNotFound(text=f"Persona '{name}' not found")

    # Read system prompt file
    prompt_path = _get_prompt_path(octo, name)
    if prompt_path and prompt_path.exists():
        system_prompt = prompt_path.read_text(encoding="utf-8")

    return {
        "page": "personas",
        "version": __version__,
        "persona": {
            "name": persona["name"],
            "display_name": persona["display_name"],
            "description": persona.get("description", ""),
        },
        "system_prompt": system_prompt,
        "prompt_path": str(prompt_path) if prompt_path else "",
    }


@routes.post("/api/personas/{name}/prompt")
async def save_prompt(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    name = request.match_info["name"]

    data = await request.post()
    content = data.get("content", "")

    prompt_path = _get_prompt_path(octo, name)
    if not prompt_path:
        raise web.HTTPNotFound(text=f"Persona '{name}' not found")

    prompt_path.write_text(content, encoding="utf-8")

    raise web.HTTPFound(f"/personas/{name}?flash=System+prompt+saved")


@routes.post("/api/personas/{name}/activate")
async def activate_persona(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    name = request.match_info["name"]

    if octo._persona_manager:
        try:
            persona = octo._persona_manager.activate(name)
            octo._persona = persona
            raise web.HTTPFound(f"/personas?flash=Switched+to+{name}")
        except (ValueError, KeyError):
            pass

    raise web.HTTPFound(f"/personas?flash=Persona+'{name}'+not+found&flash_type=error")


def _get_prompt_path(octo, persona_name: str) -> Path | None:
    """Find the system_prompt.md file for a persona."""
    # Look in the personas/ directory relative to project root
    if octo._persona_manager:
        base_dir = octo._persona_manager._personas_dir
        prompt_path = base_dir / persona_name / "system_prompt.md"
        if prompt_path.exists():
            return prompt_path
        # Try persona.yaml's directory
        yaml_path = base_dir / persona_name / "persona.yaml"
        if yaml_path.exists():
            return base_dir / persona_name / "system_prompt.md"
    return None
