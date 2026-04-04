"""Configuration loader for OpenOcto.

Resolution order:
1. config/default.yaml (shipped with the package)
2. ~/.openocto/config.yaml (user overrides)
3. Environment variables (for API keys)
4. CLI flags
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


def _resolve_env_vars(value: str) -> str:
    """Replace ${ENV_VAR} patterns with environment variable values."""
    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return re.sub(r"\$\{(\w+)\}", _replace, value)


def _resolve_env_recursive(data: dict | list | str) -> dict | list | str:
    """Recursively resolve ${ENV_VAR} patterns in config data."""
    if isinstance(data, dict):
        return {k: _resolve_env_recursive(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_env_recursive(item) for item in data]
    if isinstance(data, str):
        return _resolve_env_vars(data)
    return data


# --- Config models ---


class AudioConfig(BaseModel):
    input_device: int | str | None = None   # index or substring of device name
    output_device: int | str | None = None  # index or substring of device name
    sample_rate: int = 16000
    blocksize: int = 1280


class VADConfig(BaseModel):
    engine: str = "silero"
    threshold: float = 0.5
    silence_duration: float = 3.5
    max_recording_duration: float = 60.0
    pre_speech_buffer: float = 0.3
    mic_gain: float | None = None  # null = auto-gain, number = fixed multiplier
    rms_speech_threshold: int = 300  # RMS level above which audio counts as speech


class STTConfig(BaseModel):
    engine: str = "whisper.cpp"
    model_size: str = "small"
    language: str = "auto"
    n_threads: int = 4
    use_gpu: bool = True


class TTSConfig(BaseModel):
    engine: str = "piper"
    engines: dict[str, str] = Field(default_factory=dict)  # per-lang overrides, e.g. {ru: silero}
    models: dict[str, str] = Field(default_factory=lambda: {
        "en": "en_US-amy-medium",
        "ru": "ru_RU-irina-medium",
    })
    length_scale: float = 1.0
    sentence_silence: float = 0.3


class ClaudeConfig(BaseModel):
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"


class ProviderConfig(BaseModel):
    """Configuration for any OpenAI-compatible provider."""
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    # If true, api_key is not required (e.g. local proxy)
    no_auth: bool = False


class AIConfig(BaseModel):
    default_backend: str = "claude"
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)
    # Any number of OpenAI-compatible providers (openai, zai, claude-proxy, gemini, etc.)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    max_history: int = 20


class MemoryConfig(BaseModel):
    enabled: bool = True
    recent_window: int = 80           # messages in short-term window (40 turns)
    summarize_threshold: int = 40     # messages beyond window before summarization triggers
    max_facts: int = 50               # max user facts
    max_notes: int = 20               # max active notes
    notes_ttl_days: int = 14          # auto-resolve notes older than N days
    search_half_life_days: int = 30   # temporal decay for search results
    semantic_search: bool = True      # enable vector search (if dependencies installed)


class WakeWordConfig(BaseModel):
    enabled: bool = False
    model: str = "hey_jarvis_v0.1"  # any OpenWakeWord built-in or custom model name
    threshold: float = 0.5
    cooldown: float = 2.0           # seconds between detections


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str | None = None


class WebConfig(BaseModel):
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080


class AppConfig(BaseModel):
    persona: str = "octo"
    language: str = "auto"
    audio: AudioConfig = Field(default_factory=AudioConfig)
    wakeword: WakeWordConfig = Field(default_factory=WakeWordConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# --- Paths ---

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.yaml"
USER_CONFIG_DIR = Path.home() / ".openocto"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.yaml"
MODELS_DIR = USER_CONFIG_DIR / "models"
PERSONAS_DIR = PROJECT_ROOT / "personas"


# --- Loader ---


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts. override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration with resolution order:
    default.yaml -> ~/.openocto/config.yaml -> custom path -> env vars
    """
    data: dict = {}

    # 1. Default config
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH) as f:
            default_data = yaml.safe_load(f) or {}
            data = _deep_merge(data, default_data)

    # 2. User config
    if USER_CONFIG_PATH.exists():
        with open(USER_CONFIG_PATH) as f:
            user_data = yaml.safe_load(f) or {}
            data = _deep_merge(data, user_data)

    # 3. Custom config path (from CLI)
    if config_path:
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                custom_data = yaml.safe_load(f) or {}
                data = _deep_merge(data, custom_data)

    # 4. Resolve environment variables in all string values
    data = _resolve_env_recursive(data)

    return AppConfig(**data)
