"""Settings routes — UI preferences (theme, font size, language)."""

from __future__ import annotations

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__
from openocto.web.i18n import SUPPORTED_LANGUAGES

routes = web.RouteTableDef()


@routes.get("/settings")
@aiohttp_jinja2.template("settings.html")
async def settings_page(request: web.Request) -> dict:
    return {
        "page": "settings",
        "version": __version__,
        "supported_languages": SUPPORTED_LANGUAGES,
        "current_lang": request.cookies.get("oo-lang", "system"),
    }


@routes.post("/api/settings/language")
async def api_set_language(request: web.Request) -> web.Response:
    """Set UI language via cookie."""
    data = await request.json()
    lang = data.get("lang", "en")
    if lang not in SUPPORTED_LANGUAGES and lang != "system":
        return web.json_response({"ok": False, "error": "Unsupported language"}, status=400)

    resp = web.json_response({"ok": True, "lang": lang})
    if lang == "system":
        resp.del_cookie("oo-lang")
    else:
        resp.set_cookie("oo-lang", lang, max_age=365 * 24 * 3600, path="/")
    return resp
