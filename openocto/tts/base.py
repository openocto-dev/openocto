"""Abstract base for Text-to-Speech engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class AudioSegment:
    audio: np.ndarray    # int16 PCM
    sample_rate: int     # typically 22050 for piper


class TTSEngine(ABC):
    """Abstract text-to-speech engine."""

    @abstractmethod
    def synthesize(self, text: str) -> AudioSegment:
        """Synthesize text to speech.

        Args:
            text: Text to synthesize

        Returns:
            AudioSegment with int16 PCM audio
        """
