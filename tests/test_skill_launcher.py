"""Tests for the launcher skill — verifies whitelist enforcement."""

from unittest.mock import MagicMock, patch

import pytest

from openocto.skills.base import SkillError
from openocto.skills.launcher import LauncherSkill


class TestLauncher:
    @pytest.fixture
    def skill(self):
        return LauncherSkill({"allowed_apps": ["echo", "ls"]})

    async def test_app_not_in_whitelist_raises(self, skill):
        with pytest.raises(SkillError, match="whitelist"):
            await skill.execute(action="launch_app", name="rm")

    async def test_app_missing_binary_raises(self):
        s = LauncherSkill({"allowed_apps": ["definitely_not_real_xyz"]})
        with pytest.raises(SkillError, match="not installed"):
            await s.execute(action="launch_app", name="definitely_not_real_xyz")

    async def test_launch_app_success(self, skill):
        with patch("openocto.skills.launcher.shutil.which", return_value="/bin/echo"), \
             patch("openocto.skills.launcher.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=12345)
            result = await skill.execute(action="launch_app", name="echo", args=["hello"])
            assert "Launched" in result
            assert "12345" in result
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            assert call_args[0] == "/bin/echo"
            assert "hello" in call_args

    async def test_open_url_https(self, skill):
        with patch("openocto.skills.launcher._platform_opener", return_value=["xdg-open"]), \
             patch("openocto.skills.launcher.subprocess.Popen") as mock_popen:
            result = await skill.execute(action="open_url", url="https://example.com")
            assert "Opened" in result
            mock_popen.assert_called_once()

    async def test_open_url_rejects_non_http(self, skill):
        with pytest.raises(SkillError, match="http"):
            await skill.execute(action="open_url", url="file:///etc/passwd")

    async def test_launch_app_requires_name(self, skill):
        with pytest.raises(SkillError):
            await skill.execute(action="launch_app")

    async def test_open_url_requires_url(self, skill):
        with pytest.raises(SkillError):
            await skill.execute(action="open_url")
