"""Persona Manager — loads and manages AI assistant personas."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from openocto.config import PERSONAS_DIR

logger = logging.getLogger(__name__)


@dataclass
class Persona:
    name: str
    display_name: str
    description: str
    system_prompt: str
    voice_engine: str = "piper"
    voice_models: dict[str, str] = field(default_factory=lambda: {
        "en": "en_US-amy-medium",
        "ru": "ru_RU-irina-medium",
    })
    length_scale: float = 1.0
    sentence_silence: float = 0.3
    personality: dict = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)

    def get_voice_model(self, language: str) -> str:
        """Get the TTS model for the given language code."""
        # Try exact match first, then language prefix, then first available
        if language in self.voice_models:
            return self.voice_models[language]
        # "ru_RU" -> "ru"
        prefix = language.split("_")[0]
        if prefix in self.voice_models:
            return self.voice_models[prefix]
        # Fallback to English
        return self.voice_models.get("en", "en_US-amy-medium")


class PersonaManager:
    """Loads and manages persona configurations from YAML files."""

    def __init__(self, personas_dir: Path | None = None) -> None:
        self._personas_dir = personas_dir or PERSONAS_DIR
        self._personas: dict[str, Persona] = {}
        self._active: Persona | None = None
        self._load_all()

    def _load_all(self) -> None:
        if not self._personas_dir.exists():
            logger.warning("Personas directory not found: %s", self._personas_dir)
            return

        for persona_dir in self._personas_dir.iterdir():
            if persona_dir.is_dir() and (persona_dir / "persona.yaml").exists():
                try:
                    persona = self._load_persona(persona_dir)
                    self._personas[persona.name] = persona
                    logger.debug("Loaded persona: %s", persona.name)
                except Exception as e:
                    logger.warning("Failed to load persona from %s: %s", persona_dir, e)

        logger.info("Loaded %d persona(s): %s", len(self._personas), list(self._personas))

    def _load_persona(self, persona_dir: Path) -> Persona:
        config_path = persona_dir / "persona.yaml"
        prompt_path = persona_dir / "system_prompt.md"

        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        system_prompt = prompt_path.read_text(encoding="utf-8").strip() if prompt_path.exists() else ""

        voice = config.get("voice", {})

        return Persona(
            name=config["name"],
            display_name=config.get("display_name", config["name"]),
            description=config.get("description", ""),
            system_prompt=system_prompt,
            voice_engine=voice.get("engine", "piper"),
            voice_models=voice.get("models", {"en": "en_US-amy-medium", "ru": "ru_RU-irina-medium"}),
            length_scale=voice.get("length_scale", 1.0),
            sentence_silence=voice.get("sentence_silence", 0.3),
            personality=config.get("personality", {}),
            skills=config.get("skills", []),
        )

    def activate(self, name: str) -> Persona:
        """Activate a persona by name."""
        if name not in self._personas:
            available = list(self._personas)
            raise ValueError(
                f"Persona {name!r} not found. Available: {available}"
            )
        self._active = self._personas[name]
        logger.info("Activated persona: %s", name)
        return self._active

    def get_active(self) -> Persona:
        """Return the active persona. Raises if none is active."""
        if self._active is None:
            raise RuntimeError("No persona is active. Call activate() first.")
        return self._active

    def list_personas(self) -> list[dict]:
        return [
            {
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
            }
            for p in self._personas.values()
        ]

    @property
    def personas(self) -> dict[str, Persona]:
        return self._personas
