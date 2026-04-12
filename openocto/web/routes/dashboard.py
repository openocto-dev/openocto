"""Dashboard route — main page with pipeline state overview."""

from __future__ import annotations

import os
from pathlib import Path

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__
from openocto.config import USER_CONFIG_DIR, MODELS_DIR


def _collect_system_info() -> dict:
    """Gather CPU, RAM, disk and temperature info."""
    info: dict = {
        "cpu_percent": 0.0,
        "ram_total_gb": 0.0,
        "ram_used_gb": 0.0,
        "ram_percent": 0.0,
        "disk_total_gb": 0.0,
        "disk_used_gb": 0.0,
        "disk_free_gb": 0.0,
        "disk_percent": 0.0,
        "cpu_temp": None,
    }
    try:
        import psutil
        info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        info["ram_total_gb"] = round(mem.total / (1024 ** 3), 1)
        info["ram_used_gb"] = round(mem.used / (1024 ** 3), 1)
        info["ram_percent"] = mem.percent
        disk = psutil.disk_usage("/")
        info["disk_total_gb"] = round(disk.total / (1024 ** 3), 1)
        info["disk_used_gb"] = round(disk.used / (1024 ** 3), 1)
        info["disk_free_gb"] = round(disk.free / (1024 ** 3), 1)
        info["disk_percent"] = round(disk.percent, 1)
        temps = psutil.sensors_temperatures()
        if temps:
            # Raspberry Pi: 'cpu_thermal'; x86: 'coretemp'
            for key in ("cpu_thermal", "cpu-thermal", "coretemp"):
                if key in temps and temps[key]:
                    info["cpu_temp"] = round(temps[key][0].current, 1)
                    break
    except ImportError:
        pass
    return info

routes = web.RouteTableDef()


def _dir_size_mb(path: Path) -> float:
    """Total size of a directory in MB (non-recursive safe)."""
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except (OSError, PermissionError):
        pass
    return round(total / (1024 * 1024), 1)


def _file_size_mb(path: Path) -> float:
    """File size in MB."""
    try:
        return round(path.stat().st_size / (1024 * 1024), 1)
    except (OSError, FileNotFoundError):
        return 0.0


def _collect_stats(octo: object) -> dict:
    """Gather statistics from the running app instance."""
    hs = getattr(octo, '_history_store', None)
    pm = getattr(octo, '_persona_manager', None)
    cfg = getattr(octo, '_config', None)
    user_id = getattr(octo, '_current_user_id', None)
    persona = getattr(octo, '_persona', None)
    persona_name = persona.name if persona else "octo"

    # --- Message counts ---
    total_messages = 0
    user_messages = 0
    assistant_messages = 0
    total_users = 0
    if hs:
        try:
            rows = hs._conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()
            total_messages = rows["cnt"] if rows else 0
        except Exception:
            pass
        try:
            rows = hs._conn.execute(
                "SELECT role, COUNT(*) as cnt FROM messages GROUP BY role"
            ).fetchall()
            for r in rows:
                if r["role"] == "user":
                    user_messages = r["cnt"]
                elif r["role"] == "assistant":
                    assistant_messages = r["cnt"]
        except Exception:
            pass
        try:
            total_users = len(hs.list_users())
        except Exception:
            pass

    # --- Memory stats ---
    fact_count = 0
    note_count = 0
    summary_count = 0
    if hs and user_id:
        try:
            facts = hs.get_active_facts(user_id)
            fact_count = len(facts)
        except Exception:
            pass
        try:
            notes = hs.get_active_notes(user_id, persona_name)
            note_count = len(notes)
        except Exception:
            pass
        try:
            rows = hs._conn.execute(
                "SELECT COUNT(*) as cnt FROM conversation_summaries"
            ).fetchone()
            summary_count = rows["cnt"] if rows else 0
        except Exception:
            pass

    # --- Personas ---
    persona_count = 0
    if pm:
        try:
            persona_count = len(pm.list_personas())
        except Exception:
            pass

    # --- File system sizes ---
    db_path = USER_CONFIG_DIR / "history.db"
    db_size = _file_size_mb(db_path)
    models_size = _dir_size_mb(MODELS_DIR) if MODELS_DIR.exists() else 0.0

    # --- Engines/features ---
    tts_langs = list(getattr(octo, '_tts_engines', {}).keys())
    stt_engine = cfg.stt.engine if cfg else "—"
    stt_model = cfg.stt.model_size if cfg else "—"
    wakeword_on = cfg.wakeword.enabled if cfg else False
    memory_on = cfg.memory.enabled if cfg else False
    skills_count = 0  # placeholder for future

    # --- Messages per day (last 7 days) for sparkline ---
    daily_counts: list[dict] = []
    if hs:
        try:
            rows = hs._conn.execute(
                "SELECT DATE(created_at) as day, COUNT(*) as cnt "
                "FROM messages "
                "WHERE created_at >= DATE('now', '-6 days') "
                "GROUP BY DATE(created_at) "
                "ORDER BY day"
            ).fetchall()
            daily_counts = [{"day": r["day"], "count": r["cnt"]} for r in rows]
        except Exception:
            pass

    return {
        "total_messages": total_messages,
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "total_users": total_users,
        "fact_count": fact_count,
        "note_count": note_count,
        "summary_count": summary_count,
        "persona_count": persona_count,
        "db_size": db_size,
        "models_size": models_size,
        "tts_langs": tts_langs,
        "stt_engine": stt_engine,
        "stt_model": stt_model,
        "wakeword_on": wakeword_on,
        "memory_on": memory_on,
        "skills_count": skills_count,
        "daily_counts": daily_counts,
    }


@routes.get("/api/system-info")
async def api_system_info(request: web.Request) -> web.Response:
    """Return current system metrics as JSON (for live polling)."""
    return web.json_response(_collect_system_info())


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

    stats = _collect_stats(octo)
    system_info = _collect_system_info()

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
        "sys": system_info,
    }
