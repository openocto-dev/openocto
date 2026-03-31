"""Abstract base for Speech-to-Text engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class TranscriptionResult:
    text: str
    language: str        # detected language code: "en", "ru", etc.
    confidence: float    # 0.0-1.0, may be 0.0 if not supported by engine
    duration_ms: float   # processing time in milliseconds


class STTEngine(ABC):
    """Abstract speech-to-text engine."""

    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> TranscriptionResult:
        """Transcribe audio to text.

        Args:
            audio: int16 PCM audio data
            sample_rate: sample rate (default 16000 Hz)

        Returns:
            TranscriptionResult with text and detected language
        """
