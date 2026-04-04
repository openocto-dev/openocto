"""aiohttp application factory for the OpenOcto web admin."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp_jinja2  # type: ignore[import-untyped]
import jinja2
from aiohttp import web

from openocto.config import USER_CONFIG_PATH

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
    ):
        raise web.HTTPFound("/wizard")
    return await handler(request)


def create_web_app(octo_app: OpenOctoApp) -> web.Application:
    """Create and configure the aiohttp web application."""
    app = web.Application(middlewares=[first_run_redirect])

    # Attach the OpenOcto app instance for access from route handlers
    app["octo"] = octo_app

    # Jinja2 templates
    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    )

    # Static files
    app.router.add_static("/static", _STATIC_DIR, name="static")

    # Register all routes
    from openocto.web.routes import register_routes
    register_routes(app)

    return app
