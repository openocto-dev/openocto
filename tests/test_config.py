"""Tests for configuration loading."""

import os
from pathlib import Path

import pytest
import yaml

from openocto.config import (
    AppConfig,
    _deep_merge,
    _resolve_env_vars,
    load_config,
    DEFAULT_CONFIG_PATH,
)


class TestEnvVarResolution:
    def test_resolves_env_var(self):
        os.environ["TEST_OPENOCTO_VAR"] = "hello"
        assert _resolve_env_vars("${TEST_OPENOCTO_VAR}") == "hello"
        del os.environ["TEST_OPENOCTO_VAR"]

    def test_missing_env_var_becomes_empty(self):
        os.environ.pop("NONEXISTENT_VAR_XYZ", None)
        assert _resolve_env_vars("${NONEXISTENT_VAR_XYZ}") == ""

    def test_no_env_var_unchanged(self):
        assert _resolve_env_vars("plain text") == "plain text"

    def test_multiple_env_vars(self):
        os.environ["TEST_A"] = "foo"
        os.environ["TEST_B"] = "bar"
        assert _resolve_env_vars("${TEST_A}:${TEST_B}") == "foo:bar"
        del os.environ["TEST_A"]
        del os.environ["TEST_B"]


class TestDeepMerge:
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 3, "z": 4}}
        assert _deep_merge(base, override) == {"a": {"x": 1, "y": 3, "z": 4}}

    def test_override_replaces_non_dict(self):
        base = {"a": {"x": 1}}
        override = {"a": "string"}
        assert _deep_merge(base, override) == {"a": "string"}


class TestAppConfig:
    def test_default_values(self):
        config = AppConfig()
        assert config.persona == "octo"
        assert config.audio.sample_rate == 16000
        assert config.stt.engine == "whisper.cpp"
        assert config.tts.engine == "piper"
        assert config.ai.default_backend == "claude"

    def test_override_values(self):
        config = AppConfig(persona="hestia", ai={"default_backend": "openai"})
        assert config.persona == "hestia"
        assert config.ai.default_backend == "openai"

    def test_providers_config(self):
        config = AppConfig(ai={
            "providers": {
                "claude-proxy": {"model": "claude-sonnet-4", "base_url": "http://localhost:3456/v1", "no_auth": True},
                "gemini": {"api_key": "test", "model": "gemini-pro", "base_url": "https://example.com/v1"},
            }
        })
        assert "claude-proxy" in config.ai.providers
        assert config.ai.providers["claude-proxy"].no_auth is True
        assert config.ai.providers["claude-proxy"].model == "claude-sonnet-4"
        assert config.ai.providers["gemini"].api_key == "test"


class TestLoadConfig:
    def test_loads_default_config(self):
        config = load_config()
        assert config.persona == "octo"
        assert config.audio.sample_rate == 16000

    def test_default_config_file_exists(self):
        assert DEFAULT_CONFIG_PATH.exists(), f"Default config not found at {DEFAULT_CONFIG_PATH}"

    def test_custom_config_path(self, tmp_path):
        custom = tmp_path / "custom.yaml"
        custom.write_text(yaml.dump({"persona": "metis"}))
        config = load_config(custom)
        assert config.persona == "metis"

    def test_custom_config_merges_with_defaults(self, tmp_path):
        custom = tmp_path / "custom.yaml"
        custom.write_text(yaml.dump({"persona": "hestia"}))
        config = load_config(custom)
        # Custom value applied
        assert config.persona == "hestia"
        # Default values preserved
        assert config.audio.sample_rate == 16000
