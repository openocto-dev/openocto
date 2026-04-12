"""Tests for build_default_registry — the wiring from SkillsConfig to SkillRegistry."""

from unittest.mock import patch

import pytest

from openocto.config import SkillsConfig
from openocto.skills import build_default_registry


@pytest.fixture
def stubbed_vlc(tmp_path):
    """Force media_player to find a fake vlc binary so it loads in tests."""
    fake = tmp_path / "vlc"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    with patch("openocto.skills.media_player._find_vlc", return_value=str(fake)):
        yield


class TestBuildDefaultRegistry:
    def test_minimal_set(self):
        config = SkillsConfig(enabled=["time", "unit_converter"])
        reg = build_default_registry(config)
        names = reg.names()
        assert "get_current_time" in names
        assert "convert_units" in names
        assert len(reg) == 2

    def test_all_pure_python_skills(self):
        config = SkillsConfig(enabled=[
            "time", "unit_converter", "weather", "notes", "timer", "file_ops", "launcher",
        ])
        reg = build_default_registry(config)
        # Even with no allowed_dirs existing on host, file_ops still loads.
        assert "get_current_time" in reg.names()
        assert "convert_units" in reg.names()
        assert "get_weather" in reg.names()

    def test_media_player_loads_when_vlc_present(self, stubbed_vlc):
        config = SkillsConfig(enabled=["file_ops", "media_player"])
        reg = build_default_registry(config)
        assert "media_player" in reg.names()
        assert "file_operations" in reg.names()
        # MediaPlayer should be wired to FileOps for path validation.
        media = reg.get("media_player")
        file_ops = reg.get("file_operations")
        assert media._ctx_file_ops is file_ops

    def test_media_player_silently_skipped_when_no_vlc(self):
        with patch("openocto.skills.media_player._find_vlc", return_value=None):
            config = SkillsConfig(enabled=["media_player", "time"])
            reg = build_default_registry(config)
        assert "media_player" not in reg.names()
        assert "get_current_time" in reg.names()

    def test_unknown_skill_name_ignored(self):
        config = SkillsConfig(enabled=["time", "nonexistent_skill"])
        reg = build_default_registry(config)
        assert "get_current_time" in reg.names()
        assert len(reg) == 1

    def test_empty_enabled_list(self):
        config = SkillsConfig(enabled=[])
        reg = build_default_registry(config)
        assert len(reg) == 0
