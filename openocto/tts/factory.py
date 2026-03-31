"""Factory for creating TTS engines based on config."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openocto.config import TTSConfig
    from openocto.tts.base import TTSEngine


def create_tts_engine(lang: str, model_name: str, config: TTSConfig) -> TTSEngine:
    """Create a TTS engine for the given language.

    The engine type is resolved from config.engines[lang], falling back to config.engine.
    For Silero, model_name is the speaker name (e.g. "xenia").
    For Piper, model_name is the voice model name (e.g. "en_US-lessac-high").
    """
    engine_name = config.engines.get(lang, config.engine)

    if engine_name == "piper":
        from openocto.tts.piper import PiperTTSEngine
        return PiperTTSEngine(model_name=model_name, config=config)

    if engine_name == "silero":
        from openocto.tts.silero import SileroTTSEngine
        return SileroTTSEngine(lang=lang, speaker=model_name, config=config)

    raise ValueError(
        f"Unknown TTS engine: {engine_name!r}. "
        "Supported engines: 'piper', 'silero'."
    )
