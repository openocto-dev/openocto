"""Model downloader for STT, TTS, and VAD models."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import requests
from tqdm import tqdm

from openocto.config import MODELS_DIR

logger = logging.getLogger(__name__)

# Whisper GGML model download URLs
WHISPER_MODELS: dict[str, dict] = {
    "tiny": {
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
        "filename": "ggml-tiny.bin",
    },
    "base": {
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
        "filename": "ggml-base.bin",
    },
    "small": {
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        "filename": "ggml-small.bin",
    },
    "medium": {
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
        "filename": "ggml-medium.bin",
    },
}

# Piper voice model download URLs
PIPER_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
PIPER_MODELS: dict[str, dict] = {
    # --- English (US) — high quality ---
    "en_US-lessac-high": {
        "model_url": f"{PIPER_BASE_URL}/en/en_US/lessac/high/en_US-lessac-high.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_US/lessac/high/en_US-lessac-high.onnx.json",
        "description": "American English female, high quality (~109 MB)",
    },
    "en_US-ryan-high": {
        "model_url": f"{PIPER_BASE_URL}/en/en_US/ryan/high/en_US-ryan-high.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_US/ryan/high/en_US-ryan-high.onnx.json",
        "description": "American English male, high quality (~115 MB)",
    },
    "en_US-ljspeech-high": {
        "model_url": f"{PIPER_BASE_URL}/en/en_US/ljspeech/high/en_US-ljspeech-high.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_US/ljspeech/high/en_US-ljspeech-high.onnx.json",
        "description": "American English female (LJSpeech dataset), high quality (~109 MB)",
    },
    "en_US-libritts-high": {
        "model_url": f"{PIPER_BASE_URL}/en/en_US/libritts/high/en_US-libritts-high.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_US/libritts/high/en_US-libritts-high.onnx.json",
        "description": "American English multi-speaker (904 voices, LibriTTS dataset), high quality (~130 MB)",
    },
    # --- English (GB) — high quality ---
    "en_GB-cori-high": {
        "model_url": f"{PIPER_BASE_URL}/en/en_GB/cori/high/en_GB-cori-high.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_GB/cori/high/en_GB-cori-high.onnx.json",
        "description": "British English female, high quality (~109 MB)",
    },
    # --- English (US) — medium quality (smaller / faster) ---
    "en_US-amy-medium": {
        "model_url": f"{PIPER_BASE_URL}/en/en_US/amy/medium/en_US-amy-medium.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_US/amy/medium/en_US-amy-medium.onnx.json",
        "description": "American English female, medium quality (~60 MB)",
    },
    "en_US-ryan-medium": {
        "model_url": f"{PIPER_BASE_URL}/en/en_US/ryan/medium/en_US-ryan-medium.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_US/ryan/medium/en_US-ryan-medium.onnx.json",
        "description": "American English male, medium quality (~60 MB)",
    },
    "en_US-hfc_female-medium": {
        "model_url": f"{PIPER_BASE_URL}/en/en_US/hfc_female/medium/en_US-hfc_female-medium.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_US/hfc_female/medium/en_US-hfc_female-medium.onnx.json",
        "description": "American English female, medium quality (~60 MB)",
    },
    "en_US-hfc_male-medium": {
        "model_url": f"{PIPER_BASE_URL}/en/en_US/hfc_male/medium/en_US-hfc_male-medium.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_US/hfc_male/medium/en_US-hfc_male-medium.onnx.json",
        "description": "American English male, medium quality (~60 MB)",
    },
    # --- English (GB) — medium quality ---
    "en_GB-jenny_dioco-medium": {
        "model_url": f"{PIPER_BASE_URL}/en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx.json",
        "description": "British English female (Jenny), medium quality (~60 MB)",
    },
    "en_GB-alan-medium": {
        "model_url": f"{PIPER_BASE_URL}/en/en_GB/alan/medium/en_GB-alan-medium.onnx",
        "config_url": f"{PIPER_BASE_URL}/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json",
        "description": "British English male, medium quality (~60 MB)",
    },
    # --- Russian ---
    "ru_RU-irina-medium": {
        "model_url": f"{PIPER_BASE_URL}/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx",
        "config_url": f"{PIPER_BASE_URL}/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json",
        "description": "Russian female, medium quality (~60 MB)",
    },
    "ru_RU-denis-medium": {
        "model_url": f"{PIPER_BASE_URL}/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx",
        "config_url": f"{PIPER_BASE_URL}/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx.json",
        "description": "Russian male, medium quality (~60 MB)",
    },
    "ru_RU-dmitri-medium": {
        "model_url": f"{PIPER_BASE_URL}/ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx",
        "config_url": f"{PIPER_BASE_URL}/ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx.json",
        "description": "Russian male, medium quality (~60 MB)",
    },
    "ru_RU-ruslan-medium": {
        "model_url": f"{PIPER_BASE_URL}/ru/ru_RU/ruslan/medium/ru_RU-ruslan-medium.onnx",
        "config_url": f"{PIPER_BASE_URL}/ru/ru_RU/ruslan/medium/ru_RU-ruslan-medium.onnx.json",
        "description": "Russian male, medium quality (~60 MB)",
    },
}

# Silero VAD model
SILERO_VAD = {
    "url": "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx",
    "filename": "silero_vad.onnx",
}

# Silero TTS models (PyTorch .pt package format)
SILERO_TTS_MODELS: dict[str, dict] = {
    "ru": {
        "url": "https://models.silero.ai/models/tts/ru/v4_ru.pt",
        "filename": "v4_ru.pt",
        "speakers": ["baya", "kseniya", "xenia", "eugene"],
        "default_speaker": "xenia",
    },
    "en": {
        "url": "https://models.silero.ai/models/tts/en/v3_en.pt",
        "filename": "v3_en.pt",
        "speakers": ["en_0", "en_1", "en_2", "en_3", "en_4", "en_5", "en_6", "en_7"],
        "default_speaker": "en_0",
    },
}


def _download_file(url: str, dest: Path, desc: str = "") -> None:
    """Download a file with progress bar."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")

    logger.info("Downloading %s to %s", desc or url, dest)
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()

    total = int(response.headers.get("content-length", 0))
    with open(tmp, "wb") as f, tqdm(
        desc=desc or dest.name,
        total=total,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            bar.update(len(chunk))

    tmp.rename(dest)
    logger.info("Downloaded %s", dest)


def get_whisper_model(model_size: str) -> Path:
    """Get path to a whisper model, downloading if needed."""
    if model_size not in WHISPER_MODELS:
        raise ValueError(f"Unknown whisper model: {model_size}. Available: {list(WHISPER_MODELS)}")

    info = WHISPER_MODELS[model_size]
    dest = MODELS_DIR / "whisper" / info["filename"]

    if not dest.exists():
        _download_file(info["url"], dest, desc=f"whisper-{model_size}")

    return dest


def get_piper_model(model_name: str) -> tuple[Path, Path]:
    """Get paths to (model.onnx, model.onnx.json), downloading if needed."""
    if model_name not in PIPER_MODELS:
        raise ValueError(f"Unknown piper model: {model_name}. Available: {list(PIPER_MODELS)}")

    info = PIPER_MODELS[model_name]
    model_dir = MODELS_DIR / "piper"
    model_path = model_dir / f"{model_name}.onnx"
    config_path = model_dir / f"{model_name}.onnx.json"

    if not model_path.exists():
        _download_file(info["model_url"], model_path, desc=f"{model_name}.onnx")

    if not config_path.exists():
        _download_file(info["config_url"], config_path, desc=f"{model_name}.onnx.json")

    return model_path, config_path


def get_silero_tts_model(lang: str = "ru") -> Path:
    """Get path to Silero TTS model for the given language, downloading if needed."""
    if lang not in SILERO_TTS_MODELS:
        raise ValueError(f"No Silero TTS model for language: {lang!r}. Available: {list(SILERO_TTS_MODELS)}")

    info = SILERO_TTS_MODELS[lang]
    dest = MODELS_DIR / "silero_tts" / info["filename"]

    if not dest.exists():
        _download_file(info["url"], dest, desc=info["filename"])

    return dest


# Wake word models
# Built-in models are bundled with openwakeword — no download needed.
# Custom models (e.g. octo) must be downloaded from our release server.
WAKE_WORD_MODELS: dict[str, dict] = {
    "octo_v0.1": {
        "url": "https://huggingface.co/openocto-dev/openocto-models/resolve/main/octo_v0.1.onnx",
        "filename": "octo_v0.1.onnx",
        "builtin": False,
        "description": "Octo — custom wake word for OpenOcto",
    },
    "hey_jarvis_v0.1": {"builtin": True},
    "alexa_v0.1": {"builtin": True},
    "hey_mycroft_v0.1": {"builtin": True},
}


def get_wake_word_model(model_name: str) -> Path | None:
    """Return path to wake word model file, downloading if needed.

    Returns None for built-in openwakeword models (they need no file path).
    """
    info = WAKE_WORD_MODELS.get(model_name, {})
    if info.get("builtin", False):
        return None  # openwakeword loads built-ins by name

    if not info:
        # Unknown model — treat as built-in name and let openwakeword handle it
        return None

    dest = MODELS_DIR / "wakeword" / info["filename"]
    if not dest.exists():
        try:
            _download_file(info["url"], dest, desc=info["filename"])
        except Exception as e:
            logger.warning("Could not download wake word model %s: %s", info["filename"], e)
            return None  # caller will fall back to built-in
    return dest


def get_silero_vad_model() -> Path:
    """Get path to the Silero VAD model, downloading if needed."""
    dest = MODELS_DIR / "vad" / SILERO_VAD["filename"]

    if not dest.exists():
        _download_file(SILERO_VAD["url"], dest, desc="silero_vad.onnx")

    return dest


def _model_size_hint(model_size: str) -> str:
    hints = {"tiny": "75MB", "base": "142MB", "small": "466MB", "medium": "1.5GB"}
    return hints.get(model_size, "unknown size")
