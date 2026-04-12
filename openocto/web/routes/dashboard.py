"""Dashboard route — main page with pipeline state overview."""

from __future__ import annotations

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__
from openocto.skills.system_monitor import (
    collect_app_stats,
    collect_full_status,
    collect_system_info,
)

routes = web.RouteTableDef()


def _collect_daily_counts(octo: object) -> list[dict]:
    """Messages per day (last 7 days) for sparkline chart."""
    hs = getattr(octo, "_history_store", None)
    if not hs:
        return []
    try:
        rows = hs._conn.execute(
            "SELECT DATE(created_at) as day, COUNT(*) as cnt "
            "FROM messages "
            "WHERE created_at >= DATE('now', '-6 days') "
            "GROUP BY DATE(created_at) "
            "ORDER BY day"
        ).fetchall()
        return [{"day": r["day"], "count": r["cnt"]} for r in rows]
    except Exception:
        return []


# ── API endpoints ────────────────────────────────────────────────────────

@routes.get("/api/status")
async def api_status(request: web.Request) -> web.Response:
    """Full system + app status.  Used by dashboard, mobile app, and AI skill."""
    octo = request.app["octo"]
    status = collect_full_status(octo)
    status["app"]["daily_counts"] = _collect_daily_counts(octo)
    return web.json_response(status)


@routes.get("/api/system-info")
async def api_system_info(request: web.Request) -> web.Response:
    """System metrics only (lightweight, for live polling)."""
    return web.json_response(collect_system_info())


# ── Dashboard page ───────────────────────────────────────────────────────

@routes.get("/")
@aiohttp_jinja2.template("dashboard.html")
async def dashboard(request: web.Request) -> dict:
    octo = request.app["octo"]

    state = "idle"
    if octo._state_machine:
        state = octo._state_machine.state.value

    from openocto.web.routes import ensure_current_user
    ensure_current_user(octo)

    user_name = None
    if octo._current_user_id and octo._history_store:
        users = octo._history_store.list_users()
        for u in users:
            if u["id"] == octo._current_user_id:
                user_name = u["name"]
                break

    persona_name = None
    persona_slug = None
    if octo._persona:
        persona_name = octo._persona.display_name
        persona_slug = octo._persona.name if hasattr(octo._persona, 'name') else None
        if not persona_slug and persona_name:
            persona_slug = persona_name.lower()

    backend = octo._config.ai.default_backend

    # Collect all stats from the shared skill module
    app_stats = collect_app_stats(octo)
    sys_info = collect_system_info()

    # Build template-compatible stats dict (backward compat with template)
    stats = {
        **app_stats,
        "db_size": app_stats["db_size_mb"],
        "models_size": app_stats["models_size_mb"],
        "skills_count": 1,  # system_monitor!
        "daily_counts": _collect_daily_counts(octo),
    }

    return {
        "page": "dashboard",
        "version": __version__,
        "state": state,
        "user_name": user_name or "Not set",
        "persona_name": persona_name or "Not set",
        "persona_slug": persona_slug or "octo",
        "backend": backend,
        "web_port": octo._config.web.port,
        "stats": stats,
        "sys": sys_info,
    }
