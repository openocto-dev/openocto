"""Abstract base for wake word detectors."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class WakeWordDetector(ABC):
    """Abstract wake word detector."""

    @abstractmethod
    def process_chunk(self, audio_chunk: np.ndarray) -> bool:
        """Process one audio chunk (int16, flat).

        Returns True if wake word was detected (respects cooldown).
        """

    @abstractmethod
    def reset(self) -> None:
        """Reset detection cooldown."""
