"""Tests for wizard_data module — shared constants and pure functions."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


def test_constants_not_empty():
    """All constant lists should have at least one entry."""
    from openocto.wizard_data import (
        AI_BACKENDS,
        BACKEND_ENV_KEYS,
        OLLAMA_RECOMMENDED_MODELS,
        QUICK_DEFAULTS,
        SILERO_SPEAKERS_RU,
        TTS_VOICES_EN,
        WAKE_WORD_OPTIONS,
        WHISPER_MODEL_SIZES,
    )

    assert len(AI_BACKENDS) >= 3
    assert len(TTS_VOICES_EN) >= 4
    assert len(SILERO_SPEAKERS_RU) >= 2
    assert len(WAKE_WORD_OPTIONS) >= 2
    assert len(OLLAMA_RECOMMENDED_MODELS) >= 3
    assert len(WHISPER_MODEL_SIZES) >= 3
    assert "model_size" in QUICK_DEFAULTS
    assert "claude" in BACKEND_ENV_KEYS


def test_constants_tuple_format():
    """Each constant should be a list of (key, description) tuples."""
    from openocto.wizard_data import (
        AI_BACKENDS,
        OLLAMA_RECOMMENDED_MODELS,
        TTS_VOICES_EN,
        SILERO_SPEAKERS_RU,
        WAKE_WORD_OPTIONS,
        WHISPER_MODEL_SIZES,
    )

    for name, items in [
        ("AI_BACKENDS", AI_BACKENDS),
        ("TTS_VOICES_EN", TTS_VOICES_EN),
        ("SILERO_SPEAKERS_RU", SILERO_SPEAKERS_RU),
        ("WAKE_WORD_OPTIONS", WAKE_WORD_OPTIONS),
        ("OLLAMA_RECOMMENDED_MODELS", OLLAMA_RECOMMENDED_MODELS),
        ("WHISPER_MODEL_SIZES", WHISPER_MODEL_SIZES),
    ]:
        for item in items:
            assert isinstance(item, tuple) and len(item) == 2, f"{name}: expected (key, desc) tuple"
            assert isinstance(item[0], str), f"{name}: key should be str"
            assert isinstance(item[1], str), f"{name}: description should be str"


def test_detect_primary_lang():
    from openocto.wizard_data import detect_primary_lang

    with patch("locale.getdefaultlocale", return_value=("ru_RU", "UTF-8")):
        assert detect_primary_lang() == "ru"

    with patch("locale.getdefaultlocale", return_value=("en_US", "UTF-8")):
        assert detect_primary_lang() == "en"

    with patch("locale.getdefaultlocale", return_value=(None, None)):
        assert detect_primary_lang() == "en"


def test_is_ollama_installed():
    from openocto.wizard_data import is_ollama_installed

    with patch("shutil.which", return_value="/usr/local/bin/ollama"):
        assert is_ollama_installed() is True

    with patch("shutil.which", return_value=None):
        assert is_ollama_installed() is False


def test_list_ollama_models_not_installed():
    from openocto.wizard_data import list_ollama_models

    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert list_ollama_models() == []


def test_list_ollama_models_parses_output():
    from openocto.wizard_data import list_ollama_models
    from unittest.mock import MagicMock

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "NAME               ID              SIZE\nllama3:latest      abc123          4.7 GB\nqwen3:4b           def456          2.6 GB\n"

    with patch("subprocess.run", return_value=mock_result):
        models = list_ollama_models()
        assert models == ["llama3:latest", "qwen3:4b"]


def test_save_wizard_config(tmp_path: Path):
    from openocto.wizard_data import save_wizard_config

    config_dir = tmp_path / ".openocto"
    config_path = config_dir / "config.yaml"

    with (
        patch("openocto.wizard_data.USER_CONFIG_DIR", config_dir),
        patch("openocto.wizard_data.USER_CONFIG_PATH", config_path),
    ):
        result = save_wizard_config(
            backend="ollama",
            ollama_model="qwen3:4b",
            model_size="small",
            voice_en="en_US-amy-medium",
            voice_ru="xenia",
            primary_lang="auto",
            wakeword_enabled=True,
            wakeword_model="octo_v0.1",
        )

        assert result == config_path
        assert config_path.exists()

        with open(config_path) as f:
            data = yaml.safe_load(f)

        assert data["ai"]["default_backend"] == "ollama"
        assert data["ai"]["providers"]["ollama"]["model"] == "qwen3:4b"
        assert data["ai"]["providers"]["ollama"]["no_auth"] is True
        assert data["stt"]["model_size"] == "small"
        assert data["tts"]["models"]["en"] == "en_US-amy-medium"
        assert data["tts"]["engines"]["ru"] == "silero"
        assert data["wakeword"]["enabled"] is True
        assert data["wakeword"]["model"] == "octo_v0.1"


def test_save_wizard_config_claude_api_key(tmp_path: Path):
    from openocto.wizard_data import save_wizard_config

    config_dir = tmp_path / ".openocto"
    config_path = config_dir / "config.yaml"

    with (
        patch("openocto.wizard_data.USER_CONFIG_DIR", config_dir),
        patch("openocto.wizard_data.USER_CONFIG_PATH", config_path),
    ):
        save_wizard_config(backend="claude", api_key="sk-test-key-123")

        with open(config_path) as f:
            data = yaml.safe_load(f)

        assert data["ai"]["default_backend"] == "claude"
        assert data["ai"]["claude"]["api_key"] == "sk-test-key-123"


def test_save_wizard_config_merges_existing(tmp_path: Path):
    from openocto.wizard_data import save_wizard_config

    config_dir = tmp_path / ".openocto"
    config_path = config_dir / "config.yaml"
    config_dir.mkdir(parents=True)

    # Write existing config
    with open(config_path, "w") as f:
        yaml.dump({"custom_key": "keep_me", "ai": {"max_history": 50}}, f)

    with (
        patch("openocto.wizard_data.USER_CONFIG_DIR", config_dir),
        patch("openocto.wizard_data.USER_CONFIG_PATH", config_path),
    ):
        save_wizard_config(backend="openai", api_key="sk-openai")

        with open(config_path) as f:
            data = yaml.safe_load(f)

        # Existing keys preserved
        assert data["custom_key"] == "keep_me"
        assert data["ai"]["max_history"] == 50
        # New keys added
        assert data["ai"]["default_backend"] == "openai"
        assert data["ai"]["providers"]["openai"]["api_key"] == "sk-openai"
