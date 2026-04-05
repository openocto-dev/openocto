"""Setup wizard routes — multi-step first-run configuration."""

from __future__ import annotations

import logging

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__
from openocto.history import HistoryStore
from openocto.wizard_data import (
    AI_BACKENDS,
    BACKEND_ENV_KEYS,
    OLLAMA_RECOMMENDED_MODELS,
    QUICK_DEFAULTS,
    SILERO_SPEAKERS_RU,
    TTS_VOICES_EN,
    WAKE_WORD_OPTIONS,
    WHISPER_MODEL_SIZES,
    detect_primary_lang,
    is_ollama_installed,
    list_ollama_models,
    save_wizard_config,
)

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()

TOTAL_STEPS = 7


@routes.get("/wizard")
@aiohttp_jinja2.template("wizard.html")
async def wizard_page(request: web.Request) -> dict:
    """Render the wizard page (step 1 by default)."""
    primary_lang = detect_primary_lang()
    return {
        "page": "wizard",
        "version": __version__,
        "step": 1,
        "total_steps": TOTAL_STEPS,
        "primary_lang": primary_lang,
        # Step 1 data
        "default_user_name": __import__("getpass").getuser().capitalize(),
        # All data for client-side steps
        "ai_backends": AI_BACKENDS,
        "tts_voices_en": TTS_VOICES_EN,
        "silero_speakers_ru": SILERO_SPEAKERS_RU,
        "whisper_model_sizes": WHISPER_MODEL_SIZES,
        "wake_word_options": WAKE_WORD_OPTIONS,
        "ollama_recommended": OLLAMA_RECOMMENDED_MODELS,
        "quick_defaults": QUICK_DEFAULTS,
    }


@routes.get("/api/wizard/ollama-models")
async def api_ollama_models(request: web.Request) -> web.Response:
    """Return installed Ollama models as JSON."""
    installed = is_ollama_installed()
    models = list_ollama_models() if installed else []
    return web.json_response({
        "installed": installed,
        "models": models,
    })


@routes.post("/api/wizard/save")
async def api_wizard_save(request: web.Request) -> web.Response:
    """Save wizard configuration."""
    data = await request.json()

    # Create user if needed
    user_name = data.get("user_name", "User")
    store = HistoryStore()
    existing = store.get_user_by_name(user_name)
    if not existing:
        store.create_user(user_name, is_default=True)
    store.close()

    # Save config
    backend = data.get("backend", "claude")
    save_wizard_config(
        backend=backend,
        api_key=data.get("api_key", ""),
        ollama_model=data.get("ollama_model", ""),
        model_size=data.get("model_size", QUICK_DEFAULTS["model_size"]),
        voice_en=data.get("voice_en", QUICK_DEFAULTS["voice_en"]),
        voice_ru=data.get("voice_ru", QUICK_DEFAULTS["voice_ru"]),
        primary_lang=data.get("primary_lang", "auto"),
        wakeword_enabled=data.get("wakeword_enabled", False),
        wakeword_model=data.get("wakeword_model", ""),
    )

    # Apply calibration if provided
    calibration = data.get("calibration")
    if calibration:
        import yaml
        from openocto.config import _deep_merge, USER_CONFIG_PATH as cfg_path
        vad_update = {}
        for key in ("rms_speech_threshold", "threshold", "silence_duration"):
            if key in calibration:
                vad_update[key] = calibration[key]
        if vad_update and cfg_path.exists():
            with open(cfg_path) as f:
                existing_cfg = yaml.safe_load(f) or {}
            merged = _deep_merge(existing_cfg, {"vad": vad_update})
            with open(cfg_path, "w") as f:
                yaml.dump(merged, f, default_flow_style=False, allow_unicode=True)
            logger.info("Wizard calibration saved: %s", vad_update)

    logger.info("Wizard config saved for user %r, backend=%s", user_name, backend)
    return web.json_response({"ok": True, "redirect": "/"})
