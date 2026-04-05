"""Route registration for the web admin."""

from __future__ import annotations

from aiohttp import web


def register_routes(app: web.Application) -> None:
    """Register all route handlers."""
    from openocto.web.routes.dashboard import routes as dashboard_routes
    from openocto.web.routes.wizard import routes as wizard_routes
    from openocto.web.routes.ws import routes as ws_routes
    from openocto.web.routes.users import routes as users_routes
    from openocto.web.routes.messages import routes as messages_routes
    from openocto.web.routes.config import routes as config_routes
    from openocto.web.routes.personas import routes as personas_routes
    from openocto.web.routes.memory import routes as memory_routes
    from openocto.web.routes.legal import routes as legal_routes
    from openocto.web.routes.settings import routes as settings_routes
    from openocto.web.routes.calibration import routes as calibration_routes

    app.router.add_routes(dashboard_routes)
    app.router.add_routes(wizard_routes)
    app.router.add_routes(ws_routes)
    app.router.add_routes(users_routes)
    app.router.add_routes(messages_routes)
    app.router.add_routes(config_routes)
    app.router.add_routes(personas_routes)
    app.router.add_routes(memory_routes)
    app.router.add_routes(legal_routes)
    app.router.add_routes(settings_routes)
    app.router.add_routes(calibration_routes)
