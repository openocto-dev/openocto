"""OpenOcto Skills — extensible LLM-callable capability system.

The dispatcher is the LLM itself: each skill exposes a JSON Schema for
its parameters, the AI router translates the registry into Anthropic /
OpenAI tool format, and the model decides when to call them.

Public API:
    Skill, SkillRegistry, SkillError, SkillUnavailable, build_default_registry
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from openocto.skills.base import Skill, SkillError, SkillRegistry, SkillUnavailable

if TYPE_CHECKING:
    from openocto.config import SkillsConfig


# Maps the config name -> import path -> class.  Lazy imports so a
# missing optional dep (e.g. vlc bin) doesn't break the whole module
# load — each skill handles its own availability check at __init__.
_SKILL_TABLE: dict[str, tuple[str, str]] = {
    "time": ("openocto.skills.time_skill", "TimeSkill"),
    "weather": ("openocto.skills.weather", "WeatherSkill"),
    "unit_converter": ("openocto.skills.unit_converter", "UnitConverterSkill"),
    "notes": ("openocto.skills.notes", "NotesSkill"),
    "timer": ("openocto.skills.timer", "TimerSkill"),
    "file_ops": ("openocto.skills.file_ops", "FileOpsSkill"),
    "launcher": ("openocto.skills.launcher", "LauncherSkill"),
    "media_player": ("openocto.skills.media_player", "MediaPlayerSkill"),
}


def build_default_registry(config: "SkillsConfig") -> SkillRegistry:
    """Instantiate every enabled skill from config and return the registry.

    Skills that fail their availability check (missing binary, missing
    config) are silently dropped.  Order matters: file_ops is registered
    before media_player so the latter can bind to it via context.
    """
    import importlib

    registry = SkillRegistry()
    enabled = list(config.enabled)
    # Stable, dependency-aware order.
    priority = {
        "time": 0, "unit_converter": 1, "weather": 2, "notes": 3,
        "timer": 4, "file_ops": 5, "launcher": 6, "media_player": 7,
    }
    enabled.sort(key=lambda n: priority.get(n, 99))

    per_skill_config = {
        "time": config.time.model_dump() if config.time else {},
        "weather": config.weather.model_dump() if config.weather else {},
        "notes": {},
        "timer": {},
        "file_ops": config.file_ops.model_dump() if config.file_ops else {},
        "launcher": config.launcher.model_dump() if config.launcher else {},
        "media_player": config.media_player.model_dump() if config.media_player else {},
        "unit_converter": {},
    }

    for name in enabled:
        entry = _SKILL_TABLE.get(name)
        if not entry:
            continue
        module_path, class_name = entry
        try:
            module = importlib.import_module(module_path)
            skill_cls = getattr(module, class_name)
        except Exception:
            continue
        registry.try_register(skill_cls, per_skill_config.get(name, {}))

    # Wire FileOps -> MediaPlayer so the latter inherits the allow-list.
    media = registry.get("media_player")
    file_ops = registry.get("file_operations")
    if media is not None and file_ops is not None:
        media._ctx_file_ops = file_ops  # type: ignore[attr-defined]

    return registry


__all__ = [
    "Skill",
    "SkillRegistry",
    "SkillError",
    "SkillUnavailable",
    "build_default_registry",
]
