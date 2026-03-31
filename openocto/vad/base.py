"""Abstract base for Voice Activity Detection engines."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class VADEngine(ABC):

    @abstractmethod
    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        """Return True if the chunk contains speech."""

    @abstractmethod
    def should_stop_recording(self, audio_chunk: np.ndarray) -> bool:
        """Return True when silence has lasted long enough to stop recording."""

    @abstractmethod
    def reset(self) -> None:
        """Reset internal silence timer."""
