"""aiohttp application factory for the OpenOcto web admin."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp_jinja2  # type: ignore[import-untyped]
import jinja2
from aiohttp import web

from openocto.config import USER_CONFIG_PATH
from openocto.web.i18n import detect_language, get_translator

if TYPE_CHECKING:
    from openocto.app import OpenOctoApp

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"


@web.middleware
async def first_run_redirect(
    request: web.Request,
    handler: web.RequestHandler,
) -> web.StreamResponse:
    """Redirect to /wizard if no user config exists yet."""
    path = request.path
    if (
        not USER_CONFIG_PATH.exists()
        and not path.startswith("/wizard")
        and not path.startswith("/static")
        and not path.startswith("/ws")
        and not path.startswith("/api/wizard")
        and not path.startswith("/legal")
        and not path.startswith("/api/legal")
        and not path.startswith("/settings")
        and not path.startswith("/calibration")
        and not path.startswith("/api/calibration")
    ):
        raise web.HTTPFound("/wizard")
    return await handler(request)


@web.middleware
async def i18n_middleware(
    request: web.Request,
    handler: web.RequestHandler,
) -> web.StreamResponse:
    """Detect language and inject t() translator into request."""
    lang = detect_language(request)
    request["lang"] = lang
    request["t"] = get_translator(lang)
    return await handler(request)


async def _i18n_context(request: web.Request) -> dict:
    """Jinja2 context processor — makes t() and lang available in all templates."""
    return {
        "t": request.get("t", get_translator("en")),
        "lang": request.get("lang", "en"),
    }


def create_web_app(octo_app: OpenOctoApp) -> web.Application:
    """Create and configure the aiohttp web application."""
    app = web.Application(middlewares=[first_run_redirect, i18n_middleware])

    # Attach the OpenOcto app instance for access from route handlers
    app["octo"] = octo_app

    # Jinja2 templates with i18n context processor
    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
        context_processors=[_i18n_context, aiohttp_jinja2.request_processor],
    )

    # Static files
    app.router.add_static("/static", _STATIC_DIR, name="static")

    # Register all routes
    from openocto.web.routes import register_routes
    register_routes(app)

    return app
