"""Configuration routes — view and edit config sections."""

from __future__ import annotations

import copy
import logging
from typing import Any

import yaml
import aiohttp_jinja2
from aiohttp import web
from pathlib import Path

from openocto import __version__
from openocto.config import USER_CONFIG_PATH, AppConfig

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()

# Section metadata: key → (label, icon SVG)
SECTION_META: dict[str, tuple[str, str]] = {
    "ai": ("AI Backend", '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>'),
    "stt": ("Speech-to-Text", '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>'),
    "tts": ("Text-to-Speech", '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>'),
    "vad": ("Voice Activity Detection", '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>'),
    "audio": ("Audio Devices", '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/></svg>'),
    "wakeword": ("Wake Word", '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>'),
    "web": ("Web Admin", '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>'),
    "memory": ("Memory", '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>'),
}

# Fields that should use password-style input
_SECRET_FIELDS = {"api_key"}

# Choices for select-type fields
_FIELD_CHOICES: dict[str, list[str]] = {
    "ai.default_backend": ["claude", "openai", "ollama", "claude-proxy"],
    "stt.engine": ["whisper.cpp"],
    "stt.model_size": ["tiny", "base", "small", "medium", "large"],
    "stt.language": ["auto", "en", "ru"],
    "tts.engine": ["piper", "silero"],
    "vad.engine": ["silero"],
    "logging.level": ["DEBUG", "INFO", "WARNING", "ERROR"],
}


def _field_type(value: Any) -> str:
    """Determine form field type from Python value."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "dict"
    return "text"


def _cast_value(value: str, original: Any) -> Any:
    """Cast a string form value back to the original type."""
    if isinstance(original, bool):
        return value.lower() in ("true", "1", "on", "yes")
    if isinstance(original, int):
        return int(value) if value else 0
    if isinstance(original, float):
        return float(value) if value else 0.0
    if value == "" and original is None:
        return None
    return value


def _build_section_fields(section_key: str, section_obj: Any) -> list[dict]:
    """Build a list of field descriptors for a config section."""
    fields = []
    data = section_obj.model_dump() if hasattr(section_obj, "model_dump") else {}

    for name, value in data.items():
        full_key = f"{section_key}.{name}"
        field_info: dict[str, Any] = {
            "name": name,
            "value": value,
            "type": _field_type(value),
            "secret": name in _SECRET_FIELDS,
        }

        # Check for predefined choices
        if full_key in _FIELD_CHOICES:
            field_info["choices"] = _FIELD_CHOICES[full_key]
            field_info["type"] = "select"

        # Nested models (like ai.claude, ai.providers) → render as sub-fields
        if isinstance(value, dict):
            field_info["type"] = "dict"
            field_info["yaml_value"] = yaml.dump(
                value, default_flow_style=False, allow_unicode=True
            ).rstrip() if value else ""

        fields.append(field_info)

    return fields


@routes.get("/config")
@aiohttp_jinja2.template("config.html")
async def config_page(request: web.Request) -> dict:
    octo = request.app["octo"]

    # Read the current user config file
    user_config: dict = {}
    if USER_CONFIG_PATH.exists():
        with open(USER_CONFIG_PATH) as f:
            user_config = yaml.safe_load(f) or {}

    # Build sections with current values from the resolved config
    cfg = octo._config
    sections: dict[str, dict] = {}
    for key, (label, icon) in SECTION_META.items():
        section_obj = getattr(cfg, key, None)
        if section_obj is not None:
            sections[key] = {
                "label": label,
                "icon": icon,
                "fields": _build_section_fields(key, section_obj),
                "overridden": key in user_config,
            }

    # Top-level simple fields
    top_level = {}
    for field in ("language", "persona"):
        val = getattr(cfg, field, None)
        if val is not None:
            top_level[field] = val

    # Available personas for the persona select
    persona_names = []
    if hasattr(octo, '_persona_manager') and octo._persona_manager:
        persona_names = [p["name"] for p in octo._persona_manager.list_personas()]
    if not persona_names:
        persona_names = ["octo"]

    flash = request.query.get("flash")
    flash_type = request.query.get("flash_type", "success")

    return {
        "page": "config",
        "version": __version__,
        "sections": sections,
        "top_level": top_level,
        "persona_names": persona_names,
        "config_path": str(USER_CONFIG_PATH),
        "config_exists": USER_CONFIG_PATH.exists(),
        "flash": flash,
        "flash_type": flash_type,
    }


@routes.post("/api/config/section/{section}")
async def save_section(request: web.Request) -> web.Response:
    """Save a single config section from the form."""
    section_key = request.match_info["section"]

    # Validate section name
    valid_keys = set(SECTION_META.keys()) | {"general"}
    if section_key not in valid_keys:
        raise web.HTTPBadRequest(text=f"Unknown section: {section_key}")

    data = await request.post()
    octo = request.app["octo"]
    cfg = octo._config

    # Read existing user config
    user_config: dict = {}
    if USER_CONFIG_PATH.exists():
        with open(USER_CONFIG_PATH) as f:
            user_config = yaml.safe_load(f) or {}

    if section_key == "general":
        # Top-level fields
        for field in ("language", "persona"):
            if field in data:
                user_config[field] = data[field]
    else:
        # Get original section for type inference
        section_obj = getattr(cfg, section_key, None)
        if section_obj is None:
            raise web.HTTPBadRequest(text=f"Section not found: {section_key}")

        original_data = section_obj.model_dump() if hasattr(section_obj, "model_dump") else {}
        section_update: dict[str, Any] = {}

        for name, original_value in original_data.items():
            form_key = f"{section_key}.{name}"

            if isinstance(original_value, bool):
                # Checkboxes: present = true, absent = false
                section_update[name] = form_key in data
            elif isinstance(original_value, dict):
                # Dicts are submitted as YAML text
                yaml_key = f"{form_key}.__yaml__"
                if yaml_key in data:
                    try:
                        parsed = yaml.safe_load(data[yaml_key])
                        if isinstance(parsed, dict):
                            section_update[name] = parsed
                    except yaml.YAMLError:
                        pass  # keep original
            elif form_key in data:
                val_str = data[form_key]
                section_update[name] = _cast_value(val_str, original_value)

        user_config[section_key] = section_update

    # Validate full config
    try:
        # Merge with defaults to validate
        test_config = copy.deepcopy(user_config)
        AppConfig(**{**cfg.model_dump(), **test_config})
    except Exception as e:
        logger.warning("Config validation failed: %s", e)
        raise web.HTTPFound(
            f"/config?flash=Validation+error:+{str(e)[:200]}&flash_type=error"
        )

    # Save
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_PATH.write_text(
        yaml.dump(user_config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    raise web.HTTPFound(f"/config?flash={section_key}+saved.+Restart+to+apply.")


@routes.get("/api/config/raw")
async def config_raw(request: web.Request) -> web.Response:
    """Return raw YAML config file content."""
    if not USER_CONFIG_PATH.exists():
        return web.Response(text="# No config file yet\n", content_type="text/plain")

    content = USER_CONFIG_PATH.read_text(encoding="utf-8")
    return web.Response(text=content, content_type="text/plain")


@routes.post("/api/config/raw")
async def save_config_raw(request: web.Request) -> web.Response:
    """Save raw YAML config file."""
    data = await request.post()
    content = data.get("content", "")

    # Validate YAML before saving
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise web.HTTPFound(f"/config?flash=Invalid+YAML:+{e}&flash_type=error")

    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_PATH.write_text(content, encoding="utf-8")

    raise web.HTTPFound("/config?flash=Config+saved.+Restart+to+apply+changes.")
