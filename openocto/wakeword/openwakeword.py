"""Wake word detection using OpenWakeWord."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import numpy as np

from openocto.wakeword.base import WakeWordDetector

if TYPE_CHECKING:
    from openocto.config import WakeWordConfig

logger = logging.getLogger(__name__)

BUILTIN_FALLBACK = "hey_jarvis_v0.1"


def _ensure_builtin_downloaded(model_name: str) -> None:
    """Download openwakeword feature models + the specified built-in wake word model.

    This is idempotent — skips files that already exist.
    """
    try:
        from openwakeword.utils import download_models
        print(f"⬇️  Downloading wake word feature models...")
        download_models(model_names=[model_name])
    except Exception as e:
        logger.warning("Failed to download openwakeword models: %s", e)


class OpenWakeWordDetector(WakeWordDetector):
    """Wake word detector backed by the openwakeword library.

    Requires: pip install openocto[wakeword]
    Built-in models: hey_jarvis_v0.1, alexa_v0.1, hey_mycroft_v0.1, hey_rhasspy_v0.1
    Custom models:   octo_v0.1 (downloaded from openocto-dev HuggingFace)
    """

    def __init__(self, config: WakeWordConfig) -> None:
        try:
            from openwakeword.model import Model
        except ImportError as e:
            raise RuntimeError(
                "openwakeword is required for wake word detection. "
                "Install with: pip install openocto[wakeword]"
            ) from e

        self._threshold = config.threshold
        self._cooldown = config.cooldown
        self._last_detection: float = 0.0

        from openocto.utils.model_downloader import get_wake_word_model, WAKE_WORD_MODELS
        is_custom = not WAKE_WORD_MODELS.get(config.model, {}).get("builtin", True)
        model_path = get_wake_word_model(config.model) if is_custom else None

        # Download feature models (melspectrogram, embedding) + the selected wake word model.
        # For custom models we use BUILTIN_FALLBACK to pull the shared feature models.
        # For built-in models we download the model itself directly.
        seed = config.model if not is_custom else BUILTIN_FALLBACK
        _ensure_builtin_downloaded(seed)

        if is_custom and model_path is not None:
            # Custom model file downloaded successfully — load by path.
            self._model_name = model_path.stem
            try:
                self._oww = Model(
                    wakeword_models=[str(model_path)],
                    inference_framework="onnx",
                )
                logger.info(
                    "Wake word detector loaded: model=%s (file), threshold=%.2f",
                    self._model_name, config.threshold,
                )
                return
            except Exception as e:
                logger.warning(
                    "Failed to load custom wake word model %s: %s — falling back to %s",
                    config.model, e, BUILTIN_FALLBACK,
                )

        # Built-in model (or custom model unavailable) — load by name.
        if is_custom:
            print(f"⚠️  Wake word model '{config.model}' not available — using {BUILTIN_FALLBACK} instead.")
            builtin_name = BUILTIN_FALLBACK
        else:
            builtin_name = config.model

        self._model_name = builtin_name
        self._oww = Model(wakeword_models=[builtin_name], inference_framework="onnx")
        logger.info(
            "Wake word detector loaded: model=%s (builtin), threshold=%.2f",
            builtin_name, config.threshold,
        )

    def process_chunk(self, audio_chunk: np.ndarray) -> bool:
        """Return True if wake word detected (with cooldown)."""
        prediction = self._oww.predict(audio_chunk)
        score = float(prediction.get(self._model_name, 0.0))
        if score > 0.1:
            logger.debug("Wake word score: %.3f (threshold=%.2f)", score, self._threshold)
        now = time.monotonic()
        if score >= self._threshold and (now - self._last_detection) >= self._cooldown:
            self._last_detection = now
            logger.info("Wake word detected: score=%.3f", score)
            return True
        return False

    def reset(self) -> None:
        self._last_detection = 0.0
