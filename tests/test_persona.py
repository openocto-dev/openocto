"""Tests for the Persona Manager."""

from pathlib import Path

import pytest
import yaml

from openocto.persona.manager import Persona, PersonaManager


@pytest.fixture
def personas_dir(tmp_path: Path) -> Path:
    """Create a minimal test personas directory."""
    octo = tmp_path / "octo"
    octo.mkdir()
    (octo / "persona.yaml").write_text(yaml.dump({
        "name": "octo",
        "display_name": "Octo",
        "description": "Test persona",
        "voice": {
            "engine": "piper",
            "models": {"en": "en_US-amy-medium", "ru": "ru_RU-irina-medium"},
        },
        "personality": {"tone": "friendly"},
        "skills": ["general"],
    }))
    (octo / "system_prompt.md").write_text("You are Octo, a helpful assistant.")

    # Second persona without system_prompt.md
    minimal = tmp_path / "minimal"
    minimal.mkdir()
    (minimal / "persona.yaml").write_text(yaml.dump({
        "name": "minimal",
        "display_name": "Minimal",
        "description": "Minimal persona",
    }))

    return tmp_path


class TestPersonaManager:
    def test_loads_personas(self, personas_dir):
        pm = PersonaManager(personas_dir)
        assert "octo" in pm.personas
        assert "minimal" in pm.personas

    def test_activate(self, personas_dir):
        pm = PersonaManager(personas_dir)
        persona = pm.activate("octo")
        assert persona.name == "octo"
        assert persona.display_name == "Octo"

    def test_get_active(self, personas_dir):
        pm = PersonaManager(personas_dir)
        pm.activate("octo")
        assert pm.get_active().name == "octo"

    def test_get_active_raises_if_none(self, personas_dir):
        pm = PersonaManager(personas_dir)
        with pytest.raises(RuntimeError, match="No persona is active"):
            pm.get_active()

    def test_activate_unknown_raises(self, personas_dir):
        pm = PersonaManager(personas_dir)
        with pytest.raises(ValueError, match="not found"):
            pm.activate("nonexistent")

    def test_system_prompt_loaded(self, personas_dir):
        pm = PersonaManager(personas_dir)
        persona = pm.activate("octo")
        assert "Octo" in persona.system_prompt

    def test_system_prompt_empty_if_missing(self, personas_dir):
        pm = PersonaManager(personas_dir)
        persona = pm.activate("minimal")
        assert persona.system_prompt == ""

    def test_list_personas(self, personas_dir):
        pm = PersonaManager(personas_dir)
        listing = pm.list_personas()
        names = [p["name"] for p in listing]
        assert "octo" in names
        assert "minimal" in names

    def test_empty_dir_loads_zero_personas(self, tmp_path):
        pm = PersonaManager(tmp_path)
        assert pm.personas == {}

    def test_nonexistent_dir(self, tmp_path):
        pm = PersonaManager(tmp_path / "nonexistent")
        assert pm.personas == {}


class TestPersonaVoiceModel:
    def test_exact_language_match(self):
        p = Persona(
            name="test", display_name="Test", description="",
            system_prompt="",
            voice_models={"en": "en_US-amy-medium", "ru": "ru_RU-irina-medium"},
        )
        assert p.get_voice_model("en") == "en_US-amy-medium"
        assert p.get_voice_model("ru") == "ru_RU-irina-medium"

    def test_language_prefix_fallback(self):
        p = Persona(
            name="test", display_name="Test", description="",
            system_prompt="",
            voice_models={"en": "en_US-amy-medium"},
        )
        assert p.get_voice_model("en_US") == "en_US-amy-medium"

    def test_english_fallback(self):
        p = Persona(
            name="test", display_name="Test", description="",
            system_prompt="",
            voice_models={"en": "en_US-amy-medium"},
        )
        assert p.get_voice_model("fr") == "en_US-amy-medium"
