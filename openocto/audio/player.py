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

# Fade duration in seconds — eliminates clicks on start/stop
_FADE_SECONDS = 0.005  # 5 ms


class AudioPlayer:
    """Plays audio through the default (or configured) output device."""

    def __init__(self, config: AudioConfig | None = None) -> None:
        from openocto.audio.capture import _resolve_device
        raw = config.output_device if config else None
        self._output_device = _resolve_device(raw, kind="output")
        self._playing = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play audio synchronously (blocks until done or stopped)."""
        if audio.size == 0:
            return

        audio_float = self._to_float32(audio)
        audio_float = self._apply_fades(audio_float, sample_rate)

        with self._lock:
            self._playing = True
            self._stop_event.clear()

        try:
            # Use a dedicated OutputStream instead of global sd.play()
            # to avoid conflicts with the capture stream running in parallel
            finished_event = threading.Event()

            def _finished_callback():
                finished_event.set()

            stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                device=self._output_device,
                finished_callback=_finished_callback,
            )

            # Ensure audio is 2D (samples, channels) for OutputStream.write()
            if audio_float.ndim == 1:
                audio_float = audio_float.reshape(-1, 1)

            stream.start()
            try:
                # Write audio in chunks to allow stop interruption
                chunk_size = max(1024, sample_rate // 20)  # ~50ms chunks
                offset = 0
                while offset < len(audio_float) and not self._stop_event.is_set():
                    end = min(offset + chunk_size, len(audio_float))
                    stream.write(audio_float[offset:end])
                    offset = end

                # At this point all chunks are written; only the device's
                # output buffer remains to drain. On PipeWire/ALSA the
                # finished_callback can lag by ~1s, so the old hard 5s cap
                # added perceivable pauses between TTS and auto-listen.
                # A short bounded wait is sufficient — stream.stop() below
                # will also block until the hardware finishes.
                if not self._stop_event.is_set():
                    finished_event.wait(timeout=0.5)
            finally:
                stream.stop()
                stream.close()
        except Exception:
            logger.exception("Audio playback error")
        finally:
            with self._lock:
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

    def chime(self, ascending: bool = True, volume: float = 0.4) -> None:
        """Play a two-note chime (non-blocking).

        ascending=True  → C5 then E5 ("mic open", recording start)
        ascending=False → E5 then C5 ("mic closed", recording end)
        """
        sample_rate = 22050
        note_duration = 0.07
        gap = 0.02
        low_freq, high_freq = 523.25, 659.25  # C5, E5
        f1, f2 = (low_freq, high_freq) if ascending else (high_freq, low_freq)

        def _make_note(freq: float) -> np.ndarray:
            t = np.linspace(0, note_duration, int(sample_rate * note_duration), endpoint=False)
            tone = np.sin(2 * np.pi * freq * t).astype(np.float32)
            # Short attack + smooth release so there's no click
            attack_n = int(sample_rate * 0.005)
            release_n = int(sample_rate * 0.03)
            envelope = np.ones_like(tone)
            envelope[:attack_n] = np.linspace(0.0, 1.0, attack_n)
            envelope[-release_n:] = np.linspace(1.0, 0.0, release_n) ** 2
            return (tone * envelope * volume).astype(np.float32)

        silence = np.zeros(int(sample_rate * gap), dtype=np.float32)
        chord = np.concatenate([_make_note(f1), silence, _make_note(f2)])
        threading.Thread(target=sd.play, args=(chord, sample_rate), daemon=True).start()

    def stop(self) -> None:
        """Interrupt current playback (for barge-in)."""
        self._stop_event.set()
        with self._lock:
            self._playing = False

    @property
    def is_playing(self) -> bool:
        return self._playing

    @staticmethod
    def _apply_fades(audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """Apply short fade-in and fade-out to prevent clicks."""
        fade_samples = int(sample_rate * _FADE_SECONDS)
        if fade_samples < 2 or len(audio) < fade_samples * 2:
            return audio

        audio = audio.copy()
        # Fade-in
        fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        audio[:fade_samples] *= fade_in
        # Fade-out
        fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
        audio[-fade_samples:] *= fade_out
        return audio

    @staticmethod
    def _to_float32(audio: np.ndarray) -> np.ndarray:
        """Normalize audio to float32 [-1.0, 1.0]."""
        if audio.dtype == np.float32:
            return audio
        if audio.dtype == np.int16:
            return audio.astype(np.float32) / 32768.0
        return audio.astype(np.float32)
