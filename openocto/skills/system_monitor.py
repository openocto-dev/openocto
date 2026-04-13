"""System monitor skill — gives the assistant awareness of host system state.

Collects CPU, RAM, disk, temperature, and app-level stats (messages,
memory, personas, backends) into a compact context block that is injected
into the AI system prompt.  The same data is exposed via ``/api/status``
for the web dashboard and future mobile apps.
"""

from __future__ import annotations

import logging
import platform
from datetime import datetime
from pathlib import Path

from openocto.config import MODELS_DIR, USER_CONFIG_DIR

logger = logging.getLogger(__name__)


# ── System-level metrics ─────────────────────��──────────────────────────

def collect_system_info() -> dict:
    """CPU, RAM, disk usage and CPU temperature."""
    info: dict = {
        "hostname": platform.node(),
        "platform": f"{platform.system()} {platform.machine()}",
        "cpu_percent": 0.0,
        "cpu_count": 0,
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

        info["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        info["cpu_count"] = psutil.cpu_count() or 0
        mem = psutil.virtual_memory()
        info["ram_total_gb"] = round(mem.total / (1024 ** 3), 1)
        info["ram_used_gb"] = round(mem.used / (1024 ** 3), 1)
        info["ram_percent"] = mem.percent
        disk = psutil.disk_usage("/")
        info["disk_total_gb"] = round(disk.total / (1024 ** 3), 1)
        info["disk_used_gb"] = round(disk.used / (1024 ** 3), 1)
        info["disk_free_gb"] = round(disk.free / (1024 ** 3), 1)
        info["disk_percent"] = round(disk.percent, 1)
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if temps:
                for key in ("cpu_thermal", "cpu-thermal", "coretemp"):
                    if key in temps and temps[key]:
                        info["cpu_temp"] = round(temps[key][0].current, 1)
                        break
    except Exception:
        pass
    return info


# ── App-level stats ──────────────────────────────���───────────────────��──

def _file_size_mb(path: Path) -> float:
    try:
        return round(path.stat().st_size / (1024 * 1024), 1)
    except (OSError, FileNotFoundError):
        return 0.0


def _dir_size_mb(path: Path) -> float:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except (OSError, PermissionError):
        pass
    return round(total / (1024 * 1024), 1)


def collect_app_stats(octo: object) -> dict:
    """Gather application-level statistics from a running OpenOctoApp."""
    hs = getattr(octo, "_history_store", None)
    pm = getattr(octo, "_persona_manager", None)
    cfg = getattr(octo, "_config", None)
    user_id = getattr(octo, "_current_user_id", None)
    persona = getattr(octo, "_persona", None)
    persona_name = persona.name if persona else "octo"

    stats: dict = {
        "total_messages": 0,
        "user_messages": 0,
        "assistant_messages": 0,
        "total_users": 0,
        "fact_count": 0,
        "note_count": 0,
        "summary_count": 0,
        "persona_count": 0,
        "active_persona": persona_name,
        "active_user": None,
        "ai_backend": cfg.ai.default_backend if cfg else "—",
        "db_size_mb": 0.0,
        "models_size_mb": 0.0,
        "tts_langs": [],
        "stt_engine": cfg.stt.engine if cfg else "—",
        "stt_model": cfg.stt.model_size if cfg else "—",
        "wakeword_on": cfg.wakeword.enabled if cfg else False,
        "memory_on": cfg.memory.enabled if cfg else False,
        "pipeline_state": "idle",
    }

    # Pipeline state
    sm = getattr(octo, "_state_machine", None)
    if sm:
        stats["pipeline_state"] = sm.state.value

    # Active user name
    if hs and user_id:
        for u in hs.list_users():
            if u["id"] == user_id:
                stats["active_user"] = u["name"]
                break

    # Message counts
    if hs:
        try:
            row = hs._conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()
            stats["total_messages"] = row["cnt"] if row else 0
        except Exception:
            pass
        try:
            rows = hs._conn.execute(
                "SELECT role, COUNT(*) as cnt FROM messages GROUP BY role"
            ).fetchall()
            for r in rows:
                if r["role"] == "user":
                    stats["user_messages"] = r["cnt"]
                elif r["role"] == "assistant":
                    stats["assistant_messages"] = r["cnt"]
        except Exception:
            pass
        try:
            stats["total_users"] = len(hs.list_users())
        except Exception:
            pass

    # Memory stats
    if hs and user_id:
        try:
            stats["fact_count"] = len(hs.get_active_facts(user_id))
        except Exception:
            pass
        try:
            stats["note_count"] = len(hs.get_active_notes(user_id, persona_name))
        except Exception:
            pass
        try:
            row = hs._conn.execute(
                "SELECT COUNT(*) as cnt FROM conversation_summaries"
            ).fetchone()
            stats["summary_count"] = row["cnt"] if row else 0
        except Exception:
            pass

    # Personas
    if pm:
        try:
            stats["persona_count"] = len(pm.list_personas())
        except Exception:
            pass

    # Sizes
    stats["db_size_mb"] = _file_size_mb(USER_CONFIG_DIR / "history.db")
    if MODELS_DIR.exists():
        stats["models_size_mb"] = _dir_size_mb(MODELS_DIR)

    # TTS / engines
    stats["tts_langs"] = list(getattr(octo, "_tts_engines", {}).keys())

    return stats


# ── Combined status (for API + AI) ─────────────────────────────────────

def collect_full_status(octo: object) -> dict:
    """Full status: system info + app stats.  Used by /api/status and AI skill."""
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "system": collect_system_info(),
        "app": collect_app_stats(octo),
    }


# ── AI context builder ─────────────────────────────��────────────────────

def build_ai_context(octo: object) -> str:
    """Build a compact text block for the AI system prompt with current system state."""
    status = collect_full_status(octo)
    s = status["system"]
    a = status["app"]

    lines = [
        "## Current system state",
        f"Host: {s['hostname']} ({s['platform']})",
        f"CPU: {s['cpu_percent']}% ({s['cpu_count']} cores)",
        f"RAM: {s['ram_used_gb']}/{s['ram_total_gb']} GB ({s['ram_percent']}%)",
        f"Disk: {s['disk_used_gb']}/{s['disk_total_gb']} GB ({s['disk_percent']}% used, {s['disk_free_gb']} GB free)",
    ]
    if s["cpu_temp"] is not None:
        lines.append(f"CPU temperature: {s['cpu_temp']}°C")

    lines.append("")
    lines.append("## OpenOcto status")
    lines.append(f"Pipeline: {a['pipeline_state']}")
    lines.append(f"User: {a['active_user'] or 'unknown'}")
    lines.append(f"Persona: {a['active_persona']}")
    lines.append(f"AI backend: {a['ai_backend']}")
    lines.append(f"Messages: {a['total_messages']} total ({a['user_messages']} user, {a['assistant_messages']} assistant)")
    lines.append(f"Memory: {a['fact_count']} facts, {a['note_count']} notes, {a['summary_count']} summaries")
    lines.append(f"STT: {a['stt_engine']} ({a['stt_model']})")
    lines.append(f"TTS languages: {', '.join(a['tts_langs']) or 'none'}")
    lines.append(f"Wake word: {'on' if a['wakeword_on'] else 'off'}")
    lines.append(f"DB size: {a['db_size_mb']} MB, Models: {a['models_size_mb']} MB")

    return "\n".join(lines)
