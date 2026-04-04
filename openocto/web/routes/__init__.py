"""Route registration for the web admin."""

from __future__ import annotations

from aiohttp import web


def register_routes(app: web.Application) -> None:
    """Register all route handlers."""
    from openocto.web.routes.dashboard import routes as dashboard_routes
    from openocto.web.routes.wizard import routes as wizard_routes
    from openocto.web.routes.ws import routes as ws_routes

    app.router.add_routes(dashboard_routes)
    app.router.add_routes(wizard_routes)
    app.router.add_routes(ws_routes)
