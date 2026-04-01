"""Audio playback through speakers."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd

if TYPE_CHECKING:
    from openocto.config import AudioConfig

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Plays audio through the default (or configured) output device."""

    def __init__(self, config: AudioConfig | None = None) -> None:
        from openocto.audio.capture import _resolve_device
        raw = config.output_device if config else None
        self._output_device = _resolve_device(raw, kind="output")
        self._playing = False
        self._stop_event = threading.Event()

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play audio synchronously (blocks until done or stopped)."""
        if audio.size == 0:
            return

        audio_float = self._to_float32(audio)
        self._playing = True
        self._stop_event.clear()

        try:
            sd.play(audio_float, samplerate=sample_rate, device=self._output_device)
            # Poll for stop signal instead of blocking with sd.wait()
            while sd.get_stream().active and not self._stop_event.is_set():
                self._stop_event.wait(timeout=0.05)
        except Exception:
            logger.exception("Audio playback error")
        finally:
            sd.stop()
            self._playing = False

        logger.debug("Audio playback finished (%d samples @ %dHz)", audio.size, sample_rate)

    def play_async(self, audio: np.ndarray, sample_rate: int) -> threading.Thread:
        """Play audio in a background thread. Returns the thread."""
        thread = threading.Thread(target=self.play, args=(audio, sample_rate), daemon=True)
        thread.start()
        return thread

    async def play_async_awaitable(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play audio in a thread pool and await completion."""
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.play, audio, sample_rate)

    def beep(self, freq: float = 880.0, duration: float = 0.12, volume: float = 0.4) -> None:
        """Play a short sine-wave beep (non-blocking)."""
        sample_rate = 22050
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        # Sine with quick fade-out to avoid click
        tone = np.sin(2 * np.pi * freq * t).astype(np.float32)
        fade = np.linspace(1.0, 0.0, len(tone)) ** 2
        tone = (tone * fade * volume).astype(np.float32)
        threading.Thread(target=sd.play, args=(tone, sample_rate), daemon=True).start()

    def stop(self) -> None:
        """Interrupt current playback (for barge-in)."""
        self._stop_event.set()
        sd.stop()
        self._playing = False

    @property
    def is_playing(self) -> bool:
        return self._playing

    @staticmethod
    def _to_float32(audio: np.ndarray) -> np.ndarray:
        """Normalize audio to float32 [-1.0, 1.0]."""
        if audio.dtype == np.float32:
            return audio
        if audio.dtype == np.int16:
            return audio.astype(np.float32) / 32768.0
        return audio.astype(np.float32)
