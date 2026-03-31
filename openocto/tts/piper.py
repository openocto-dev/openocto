"""Text-to-Speech using piper-tts."""

from __future__ import annotations

import logging
import subprocess
import wave
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from openocto.tts.base import AudioSegment, TTSEngine
from openocto.utils.model_downloader import get_piper_model

if TYPE_CHECKING:
    from openocto.config import TTSConfig

logger = logging.getLogger(__name__)


class PiperTTSEngine(TTSEngine):
    """TTS engine using piper-tts.

    Tries the Python API first; falls back to CLI binary if unavailable.
    """

    def __init__(self, model_name: str, config: TTSConfig | None = None) -> None:
        self._model_name = model_name
        self._length_scale = config.length_scale if config else 1.0
        self._sentence_silence = config.sentence_silence if config else 0.3
        self._voice = None
        self._sample_rate = 22050  # piper default

        model_path, config_path = get_piper_model(model_name)

        try:
            self._load_python_api(model_path, config_path)
            logger.info("Piper loaded via Python API: %s", model_name)
        except Exception as e:
            logger.warning("Piper Python API unavailable (%s), falling back to CLI", e)
            self._model_path = model_path
            self._voice = None  # signals CLI mode

    def _load_python_api(self, model_path: Path, config_path: Path) -> None:
        from piper import PiperVoice
        self._voice = PiperVoice.load(str(model_path), config_path=str(config_path))
        # Read sample rate from the voice config
        if hasattr(self._voice, "config") and hasattr(self._voice.config, "sample_rate"):
            self._sample_rate = self._voice.config.sample_rate

    def synthesize(self, text: str) -> AudioSegment:
        """Synthesize text to speech."""
        if not text.strip():
            return AudioSegment(audio=np.zeros(0, dtype=np.int16), sample_rate=self._sample_rate)

        if self._voice is not None:
            return self._synthesize_python(text)
        return self._synthesize_cli(text)

    def _synthesize_python(self, text: str) -> AudioSegment:
        """Synthesize using the Python API."""
        from piper.config import SynthesisConfig
        syn_config = SynthesisConfig(length_scale=self._length_scale)
        chunks = list(self._voice.synthesize(text, syn_config=syn_config))
        audio = np.concatenate([c.audio_int16_array for c in chunks]) if chunks else np.zeros(0, dtype=np.int16)
        return AudioSegment(audio=audio, sample_rate=self._sample_rate)

    def _synthesize_cli(self, text: str) -> AudioSegment:
        """Synthesize using the piper CLI binary (fallback)."""
        import shutil
        piper_bin = shutil.which("piper") or shutil.which("piper-tts")
        if not piper_bin:
            raise RuntimeError(
                "piper CLI not found. Install with: pip install piper-tts "
                "or download the binary from https://github.com/rhasspy/piper/releases"
            )

        result = subprocess.run(
            [
                piper_bin,
                "--model", str(self._model_path),
                "--output-raw",
                "--length-scale", str(self._length_scale),
            ],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0:
            raise RuntimeError(f"piper CLI failed: {result.stderr.decode()}")

        audio = np.frombuffer(result.stdout, dtype=np.int16)
        return AudioSegment(audio=audio, sample_rate=self._sample_rate)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate
