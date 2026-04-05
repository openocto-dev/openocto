"""Settings routes — UI preferences (theme, font size, etc.)."""

from __future__ import annotations

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__

routes = web.RouteTableDef()


@routes.get("/settings")
@aiohttp_jinja2.template("settings.html")
async def settings_page(request: web.Request) -> dict:
    return {
        "page": "settings",
        "version": __version__,
    }
