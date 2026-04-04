"""Voice Activity Detection using Silero VAD."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import numpy as np

from openocto.vad.base import VADEngine
from openocto.utils.model_downloader import get_silero_vad_model

if TYPE_CHECKING:
    from openocto.config import VADConfig

logger = logging.getLogger(__name__)


class SileroVAD(VADEngine):
    """VAD using the Silero VAD ONNX model.

    Supports both v4 (inputs: h, c) and v5 (input: state).
    v5 requires exactly 512 samples per inference call, so larger chunks
    are split internally.
    """

    _V5_WINDOW = 512  # v5 model requires exactly 512 samples per call

    _AUTO_GAIN_NOISE_FLOOR = 0.005  # ~164 in int16 — below this, don't boost
    _AUTO_GAIN_TARGET = 0.5         # target peak for auto-gain normalization

    def __init__(self, config: VADConfig | None = None) -> None:
        self._threshold = config.threshold if config else 0.5
        self._silence_duration = config.silence_duration if config else 3.5
        self._mic_gain: float | None = config.mic_gain if config else None
        self._rms_threshold: int = config.rms_speech_threshold if config else 300
        self._sample_rate = np.array(16000, dtype=np.int64)
        self._silence_start: float | None = None
        self.last_prob: float = 0.0

        model_path = get_silero_vad_model()
        import onnxruntime as ort
        self._session = ort.InferenceSession(str(model_path))
        self._version = self._detect_model_version()
        self._reset_state()
        logger.info("Silero VAD loaded (model %s)", self._version)

    def _detect_model_version(self) -> str:
        names = {i.name for i in self._session.get_inputs()}
        if "state" in names:
            return "v5"
        return "v4"

    def _reset_state(self) -> None:
        if self._version == "v5":
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
        else:
            self._h = np.zeros((2, 1, 64), dtype=np.float32)
            self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def _infer_v5(self, audio_f32: np.ndarray) -> float:
        """Run v5 inference on exactly 512-sample windows, return max speech prob."""
        max_prob = 0.0
        for offset in range(0, len(audio_f32), self._V5_WINDOW):
            window = audio_f32[offset:offset + self._V5_WINDOW]
            if len(window) < self._V5_WINDOW:
                window = np.pad(window, (0, self._V5_WINDOW - len(window)))
            output, self._state = self._session.run(
                None,
                {"input": window.reshape(1, -1), "state": self._state, "sr": self._sample_rate},
            )
            max_prob = max(max_prob, float(output.flat[0]))
        return max_prob

    def _infer_v4(self, audio_f32: np.ndarray) -> float:
        """Run v4 inference on the full chunk."""
        output, self._h, self._c = self._session.run(
            None,
            {"input": audio_f32.reshape(1, -1), "sr": self._sample_rate, "h": self._h, "c": self._c},
        )
        return float(output.flat[0])

    def _apply_gain(self, audio_f32: np.ndarray) -> np.ndarray:
        """Apply mic gain: fixed multiplier or auto-gain based on peak."""
        if self._mic_gain is not None:
            return np.clip(audio_f32 * self._mic_gain, -1.0, 1.0)
        # Auto-gain: boost speech-level chunks, leave silence alone
        peak = np.abs(audio_f32).max()
        if peak > self._AUTO_GAIN_NOISE_FLOOR:
            gain = self._AUTO_GAIN_TARGET / peak
            return np.clip(audio_f32 * gain, -1.0, 1.0)
        return audio_f32

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        """Return True if speech detected by Silero VAD or raw RMS exceeds threshold.

        On some platforms (e.g. ARM64 onnxruntime) Silero VAD probabilities
        can be unreliable, so RMS on the RAW signal (before gain) acts as fallback.
        Gain is only applied to audio fed to the Silero model.
        """
        chunk_i16 = audio_chunk.flatten()

        # RMS on raw signal (before gain) — reliable speech/silence discriminator
        rms_raw = float(np.sqrt(np.mean(chunk_i16.astype(np.float32) ** 2)))

        # Silero inference on gained signal
        audio_f32 = chunk_i16.astype(np.float32) / 32768.0
        audio_f32 = self._apply_gain(audio_f32)
        prob = self._infer_v5(audio_f32) if self._version == "v5" else self._infer_v4(audio_f32)
        self.last_prob = prob
        self.last_rms = rms_raw

        result = prob > self._threshold or rms_raw > self._rms_threshold
        logger.debug("VAD prob=%.3f rms_raw=%.0f (thr=%d) → %s",
                      prob, rms_raw, self._rms_threshold, result)
        return result

    def should_stop_recording(self, audio_chunk: np.ndarray, speech: bool | None = None) -> bool:
        """Return True when silence has lasted >= silence_duration seconds.

        Pass ``speech`` to avoid re-running inference on the same chunk.
        """
        if speech is None:
            speech = self.is_speech(audio_chunk)

        if speech:
            self._silence_start = None
            return False

        if self._silence_start is None:
            self._silence_start = time.monotonic()

        return (time.monotonic() - self._silence_start) >= self._silence_duration

    def reset(self) -> None:
        self._silence_start = None
        self._reset_state()
