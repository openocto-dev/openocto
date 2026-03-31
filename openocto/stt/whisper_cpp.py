"""Speech-to-Text using whisper.cpp via pywhispercpp."""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

import numpy as np

from openocto.stt.base import STTEngine, TranscriptionResult
from openocto.utils.model_downloader import get_whisper_model

if TYPE_CHECKING:
    from openocto.config import STTConfig

logger = logging.getLogger(__name__)

# Whisper hallucinates on silence/noise — filter these out.
# Patterns cover common hallucinations in English, Russian, and other languages.
_HALLUCINATION_RE = re.compile(
    r"^[\s\*\[\(]*"           # leading whitespace, *, [, (
    r"("
    r"\[.*?\]"                # [sound of door], [music], [applause], [звук двери], [музыка]
    r"|\(.*?\)"               # (music), (silence), (музыка), (тишина)
    r"|\*.*?\*"               # *show*, *sound*, *показать*, *звук*
    r"|subtitl\w*"            # subtitles, subtitle
    r"|субтитр\w*"            # субтитры (Russian: subtitles)
    r"|продолжение следует"   # Russian: to be continued
    r"|to\s*be\s*continued"
    r"|thank\s*you\s*(for\s*watching)?"
    r"|please\s*(like|subscribe|share)"
    r"|don'?t\s*forget\s*to"
    r"|подписывайтесь"        # Russian: subscribe
    r")"
    r"[\s\.\,\!\*\]\)]*$",   # trailing junk
    re.IGNORECASE,
)


class WhisperCppEngine(STTEngine):
    """STT engine using whisper.cpp."""

    def __init__(self, config: STTConfig | None = None) -> None:
        model_size = config.model_size if config else "small"
        n_threads = config.n_threads if config else 4
        language = config.language if config else "auto"

        self._language = None if language == "auto" else language

        model_path = get_whisper_model(model_size)
        logger.info("Loading Whisper model: %s", model_path)

        from pywhispercpp.model import Model
        self._model = Model(str(model_path), n_threads=n_threads, print_progress=False)

        logger.info("Whisper model loaded")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> TranscriptionResult:
        """Transcribe audio to text with automatic language detection."""
        if audio.size == 0:
            return TranscriptionResult(text="", language="en", confidence=0.0, duration_ms=0.0)

        # whisper.cpp expects float32 normalized to [-1.0, 1.0]
        if audio.dtype == np.int16:
            audio_float = audio.astype(np.float32) / 32768.0
        else:
            audio_float = audio.astype(np.float32)

        start = time.perf_counter()
        segments = self._model.transcribe(
            audio_float,
            language=self._language,
        )
        duration_ms = (time.perf_counter() - start) * 1000

        text = " ".join(seg.text for seg in segments).strip()

        # Filter whisper hallucinations on silence/noise
        if text and _HALLUCINATION_RE.match(text):
            logger.debug("Filtered hallucination: %r", text)
            text = ""

        # pywhispercpp exposes detected language via the model's full params
        # Try to get it, fall back to "en"
        detected_language = self._language or self._get_detected_language()

        logger.debug(
            "Transcribed in %.0fms [%s]: %r",
            duration_ms,
            detected_language,
            text[:80],
        )

        return TranscriptionResult(
            text=text,
            language=detected_language,
            confidence=0.0,  # whisper.cpp doesn't expose per-segment confidence easily
            duration_ms=duration_ms,
        )

    def _get_detected_language(self) -> str:
        """Try to read the language detected by the last transcription."""
        try:
            # pywhispercpp >= 1.3 exposes this via the model params
            lang_id = self._model.context.full_lang_id()
            from pywhispercpp import LANGUAGES
            return LANGUAGES.get(lang_id, "en")
        except Exception:
            return "en"
