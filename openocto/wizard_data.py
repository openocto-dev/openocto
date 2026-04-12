"""Shared constants and pure functions for CLI and web setup wizards."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml

from openocto.config import USER_CONFIG_DIR, USER_CONFIG_PATH, _deep_merge


# ---------------------------------------------------------------------------
# Voice options
# ---------------------------------------------------------------------------

TTS_VOICES_EN = [
    ("en_US-lessac-high", "Lessac (female, US, high quality) ~109 MB"),
    ("en_US-ryan-high", "Ryan (male, US, high quality) ~115 MB"),
    ("en_GB-cori-high", "Cori (female, GB, high quality) ~109 MB"),
    ("en_US-ljspeech-high", "LJSpeech (female, US, high quality) ~109 MB"),
    ("en_US-hfc_female-medium", "HFC Female (US, medium) ~60 MB"),
    ("en_US-hfc_male-medium", "HFC Male (US, medium) ~60 MB"),
    ("en_GB-jenny_dioco-medium", "Jenny (female, GB, medium) ~60 MB"),
    ("en_US-amy-medium", "Amy (female, US, medium) ~60 MB"),
]

SILERO_SPEAKERS_RU = [
    ("xenia", "Xenia (female)"),
    ("baya", "Baya (female)"),
    ("kseniya", "Kseniya (female)"),
    ("eugene", "Eugene (male)"),
]

# ---------------------------------------------------------------------------
# AI backends
# ---------------------------------------------------------------------------

AI_BACKENDS = [
    ("claude-proxy", "Claude via subscription (local proxy, no API key)"),
    ("claude", "Claude API (requires ANTHROPIC_API_KEY)"),
    ("openai", "OpenAI (requires OPENAI_API_KEY)"),
    ("ollama", "Ollama (local LLM, no API key)"),
]

BACKEND_ENV_KEYS: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# ---------------------------------------------------------------------------
# Wake word options
# ---------------------------------------------------------------------------

WAKE_WORD_OPTIONS = [
    ("octo_v0.1", "Hi Octo"),
    ("hey_jarvis_v0.1", "Hey Jarvis (built-in)"),
    ("alexa_v0.1", "Alexa (built-in)"),
    ("hey_mycroft_v0.1", "Hey Mycroft (built-in)"),
]

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

OLLAMA_RECOMMENDED_MODELS = [
    ("qwen3:4b", "Qwen 3 4B — best for Russian, fits RPi 5 8GB (2.6 GB)"),
    ("qwen3:1.7b", "Qwen 3 1.7B — fastest with good Russian (1.5 GB)"),
    ("llama3.2", "Llama 3.2 3B — fast, good quality, English-focused (2 GB)"),
    ("gemma3", "Gemma 3 4B — good balance of speed and quality (3 GB)"),
    ("qwen3", "Qwen 3 8B — best quality, needs 8+ GB RAM (4.9 GB)"),
    ("mistral", "Mistral 7B — solid general purpose (4 GB)"),
]

# ---------------------------------------------------------------------------
# STT model sizes
# ---------------------------------------------------------------------------

WHISPER_MODEL_SIZES = [
    ("tiny", "Tiny — fastest, lowest quality (~75 MB)"),
    ("base", "Base — fast, decent quality (~140 MB)"),
    ("small", "Small — balanced speed and quality (~460 MB)"),
    ("medium", "Medium — best quality, slower (~1.5 GB)"),
]

# ---------------------------------------------------------------------------
# Quick setup defaults
# ---------------------------------------------------------------------------

QUICK_DEFAULTS = {
    "model_size": "small",
    "voice_en": TTS_VOICES_EN[0][0],
    "voice_ru": SILERO_SPEAKERS_RU[0][0],
    "wakeword_enabled": True,
    "wakeword_model": "octo_v0.1",
}

# ---------------------------------------------------------------------------
# Pure helper functions (no CLI I/O)
# ---------------------------------------------------------------------------


def detect_primary_lang() -> str:
    """Detect primary language from system locale."""
    import locale
    sys_locale = (locale.getdefaultlocale()[0] or "en").lower()
    return "ru" if sys_locale.startswith("ru") else "en"


def is_torch_available() -> bool:
    """Check if PyTorch is importable (needed for Silero TTS)."""
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def is_ollama_installed() -> bool:
    """Check if ollama binary is available."""
    return shutil.which("ollama") is not None


def list_ollama_models() -> list[str]:
    """Query Ollama for installed models. Returns list of model names."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        models = []
        for line in result.stdout.strip().splitlines()[1:]:  # skip header
            name = line.split()[0]
            if name:
                models.append(name)
        return models
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def save_wizard_config(
    *,
    backend: str,
    api_key: str = "",
    ollama_model: str = "",
    model_size: str = "small",
    voice_en: str = "",
    voice_ru: str = "",
    primary_lang: str = "auto",
    input_device: int | str | None = None,
    output_device: int | str | None = None,
    wakeword_enabled: bool = False,
    wakeword_model: str = "",
    mic_gain: float | None = None,
    vad_threshold: float = 0.3,
    rms_threshold: int = 300,
) -> Path:
    """Build and save wizard config to ~/.openocto/config.yaml. Returns config path."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    tts_config: dict = {}
    if voice_en or voice_ru:
        tts_config["models"] = {}
        if voice_en:
            tts_config["models"]["en"] = voice_en
        if voice_ru:
            tts_config["models"]["ru"] = voice_ru
    if primary_lang in ("ru", "auto") and is_torch_available():
        tts_config["engines"] = {"ru": "silero"}

    audio_config: dict = {}
    if input_device is not None:
        audio_config["input_device"] = input_device
    if output_device is not None:
        audio_config["output_device"] = output_device

    config: dict = {
        "language": primary_lang,
        "ai": {"default_backend": backend},
        "stt": {"model_size": model_size, "language": primary_lang},
    }
    if tts_config:
        config["tts"] = tts_config
    if audio_config:
        config["audio"] = audio_config

    vad_config: dict = {"threshold": vad_threshold, "rms_speech_threshold": rms_threshold}
    if mic_gain is not None:
        vad_config["mic_gain"] = mic_gain
    config["vad"] = vad_config

    if wakeword_enabled and wakeword_model:
        config["wakeword"] = {"enabled": True, "model": wakeword_model}

    # Store API key / provider config
    if backend == "ollama" and ollama_model:
        config["ai"].setdefault("providers", {})
        config["ai"]["providers"]["ollama"] = {
            "model": ollama_model,
            "base_url": "http://localhost:11434/v1",
            "no_auth": True,
        }
    elif api_key:
        env_var = BACKEND_ENV_KEYS.get(backend, "")
        if backend == "claude":
            config["ai"]["claude"] = {"api_key": api_key}
        elif env_var:
            config["ai"].setdefault("providers", {})
            config["ai"]["providers"][backend] = {"api_key": api_key}

    # Merge with existing config if present
    if USER_CONFIG_PATH.exists():
        with open(USER_CONFIG_PATH) as f:
            existing = yaml.safe_load(f) or {}
        config = _deep_merge(existing, config)

    with open(USER_CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    return USER_CONFIG_PATH
