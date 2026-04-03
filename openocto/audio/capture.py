"""Audio capture from microphone."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd

if TYPE_CHECKING:
    from openocto.config import AudioConfig

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
BLOCKSIZE = 1280  # 80ms chunks


def _resolve_device(device: int | str | None, kind: str) -> int | None:
    """Resolve a device name substring to its index.

    If ``device`` is already an int or None, return as-is.
    If it's a string, search for the first device whose name contains it
    (case-insensitive) and has at least one channel of the requested kind.
    Logs a warning and returns None (system default) if not found.
    """
    if device is None or isinstance(device, int):
        return device

    max_ch_key = "max_input_channels" if kind == "input" else "max_output_channels"
    devices = sd.query_devices()
    needle = device.lower()
    for idx, info in enumerate(devices):
        if needle in info["name"].lower() and info[max_ch_key] > 0:
            logger.info("Resolved %s device %r → #%d (%s)", kind, device, idx, info["name"])
            return idx

    logger.warning("Audio %s device %r not found, using system default", kind, device)
    return None


class AudioCapture:
    """Captures audio from the default (or configured) microphone."""

    def __init__(self, config: AudioConfig | None = None) -> None:
        self._sample_rate = config.sample_rate if config else SAMPLE_RATE
        self._blocksize = config.blocksize if config else BLOCKSIZE
        raw = config.input_device if config else None
        self._input_device = _resolve_device(raw, kind="input")

        self._buffer: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._recording = False
        self._chunk_callback = None  # called with every chunk (for wake word)

    def set_chunk_callback(self, callback) -> None:
        """Register a callback invoked with every audio chunk (flat int16 array).

        Called from the audio thread — must be thread-safe and non-blocking.
        Used for continuous wake word detection.
        """
        self._chunk_callback = callback

    def _callback(self, indata: np.ndarray, frames: int, time: object, status: object) -> None:
        try:
            if status:
                logger.warning("Audio capture status: %s", status)
            mono = indata[:, 0] if indata.ndim > 1 else indata.flatten()
            # Apply mic gain before passing to VAD and recording buffer
            mono_f32 = mono.astype(np.float32) / 32768.0
            mono_f32 = self._apply_gain(mono_f32)
            mono = np.clip(mono_f32 * 32768.0, -32768, 32767).astype(np.int16)
            if self._chunk_callback:
                self._chunk_callback(mono.copy())
            if self._recording:
                with self._lock:
                    self._buffer.append(mono.copy())
        except Exception as e:
            logger.error("Audio callback error: %s", e)

    def _open_stream(self) -> None:
        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=self._blocksize,
                device=self._input_device,
                callback=self._callback,
            )
        except sd.PortAudioError as e:
            if self._input_device is not None:
                logger.warning(
                    "Failed to open device %s (%s), falling back to default device",
                    self._input_device, e,
                )
                self._input_device = None
                self._stream = sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    blocksize=self._blocksize,
                    device=None,
                    callback=self._callback,
                )
            else:
                raise
        self._stream.start()

    # --- Wake word mode: keep stream always-on, control buffering separately ---

    def start_stream(self) -> None:
        """Open microphone stream without buffering (for wake word mode)."""
        if not self._stream:
            self._open_stream()
            logger.debug("Audio stream opened (always-on)")

    def stop_stream(self) -> None:
        """Close the microphone stream."""
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            logger.debug("Audio stream closed")

    def start_recording(self) -> None:
        """Start buffering audio. Stream must already be open (wake word mode)."""
        with self._lock:
            self._buffer.clear()
        self._recording = True
        logger.debug("Recording started")

    def stop_recording(self) -> np.ndarray:
        """Stop buffering and return captured audio."""
        self._recording = False
        logger.debug("Recording stopped")
        return self.get_recording()

    # --- PTT mode: open/close stream per recording ---

    def start(self) -> None:
        """Open stream and start recording (PTT mode)."""
        with self._lock:
            self._buffer.clear()
        self._recording = True
        self._open_stream()
        logger.debug("Audio capture started")

    def stop(self) -> None:
        """Stop recording and close stream (PTT mode)."""
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.debug("Audio capture stopped")

    def get_recording(self) -> np.ndarray:
        """Return the recorded audio as a single concatenated array."""
        with self._lock:
            if not self._buffer:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(self._buffer, axis=0).flatten()

    def get_latest_chunk(self, after: int = -1) -> tuple[np.ndarray, int] | None:
        """Return the next unprocessed audio chunk for VAD streaming.

        Args:
            after: index of the last processed chunk (-1 = start from beginning).

        Returns:
            (chunk, index) or None if no new chunk is available.
        """
        with self._lock:
            next_idx = after + 1
            if next_idx < len(self._buffer):
                return self._buffer[next_idx].copy(), next_idx
            return None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def is_recording(self) -> bool:
        return self._recording
