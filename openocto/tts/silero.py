"""Text-to-Speech using Silero TTS (PyTorch)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from openocto.tts.base import AudioSegment, TTSEngine

if TYPE_CHECKING:
    from openocto.config import TTSConfig

logger = logging.getLogger(__name__)

SILERO_SAMPLE_RATE = 24000


class SileroTTSEngine(TTSEngine):
    """TTS engine using Silero TTS PyTorch models.

    Requires torch. Install with: pip install torch --index-url https://download.pytorch.org/whl/cpu
    """

    def __init__(self, lang: str, speaker: str, config: TTSConfig | None = None) -> None:
        self._lang = lang
        self._speaker = speaker
        self._sample_rate = SILERO_SAMPLE_RATE

        try:
            import torch
        except ImportError as e:
            raise RuntimeError(
                "torch is required for Silero TTS. "
                "Install with: pip install torch --index-url https://download.pytorch.org/whl/cpu"
            ) from e

        from openocto.utils.model_downloader import get_silero_tts_model
        model_path = get_silero_tts_model(lang)

        self._model = torch.package.PackageImporter(str(model_path)).load_pickle("tts_models", "model")
        self._model.to(torch.device("cpu"))
        logger.info("Silero TTS loaded: lang=%s, speaker=%s", lang, speaker)

    def synthesize(self, text: str) -> AudioSegment:
        if not text.strip():
            return AudioSegment(audio=np.zeros(0, dtype=np.int16), sample_rate=self._sample_rate)

        import torch
        with torch.inference_mode():
            audio_tensor = self._model.apply_tts(
                text=text,
                speaker=self._speaker,
                sample_rate=self._sample_rate,
            )

        audio_int16 = (audio_tensor.numpy() * 32767).astype(np.int16)
        return AudioSegment(audio=audio_int16, sample_rate=self._sample_rate)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate
