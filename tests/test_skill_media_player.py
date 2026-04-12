"""Tests for the media_player skill — verifies VLC subprocess + RC contract.

Mocks ``subprocess.Popen`` and ``socket.create_connection`` so the tests
don't need an actual VLC binary or display.
"""

from unittest.mock import MagicMock, patch

import pytest

from openocto.skills.base import SkillError, SkillUnavailable
from openocto.skills.media_player import MediaPlayerSkill


@pytest.fixture
def skill(tmp_path):
    """MediaPlayerSkill with VLC discovery mocked to a fake binary."""
    media = tmp_path / "media"
    media.mkdir()
    video = media / "movie.mp4"
    video.write_bytes(b"fake")

    fake_vlc = tmp_path / "fake_vlc"
    fake_vlc.write_text("#!/bin/sh\nexit 0\n")
    fake_vlc.chmod(0o755)

    with patch("openocto.skills.media_player._find_vlc", return_value=str(fake_vlc)):
        s = MediaPlayerSkill({"binary": str(fake_vlc), "fullscreen_default": True})

    # Wire FileOps allow-list so _validate_file accepts media/movie.mp4.
    from openocto.skills.file_ops import FileOpsSkill
    s._ctx_file_ops = FileOpsSkill({"allowed_dirs": [str(media)]})
    return s, video


class TestMediaPlayerInit:
    def test_unavailable_when_no_vlc(self):
        with patch("openocto.skills.media_player._find_vlc", return_value=None):
            with pytest.raises(SkillUnavailable):
                MediaPlayerSkill()


class TestMediaPlayerCommands:
    async def test_play_spawns_vlc_with_fullscreen(self, skill):
        s, video = skill
        with patch("openocto.skills.media_player.subprocess.Popen") as mock_popen, \
             patch("openocto.skills.media_player.asyncio.sleep"):
            mock_popen.return_value = MagicMock(poll=lambda: None, pid=999)
            result = await s.execute(action="play", file=str(video))
            assert "Playing" in result
            assert "movie.mp4" in result

            cmd = mock_popen.call_args[0][0]
            assert "--fullscreen" in cmd
            assert "--extraintf" in cmd
            assert "rc" in cmd
            assert str(video) in cmd

    async def test_play_outside_allowed_raises(self, skill, tmp_path):
        s, _ = skill
        evil = tmp_path / "evil.mp4"
        evil.write_bytes(b"x")
        with pytest.raises(SkillError, match="outside allowed"):
            await s.execute(action="play", file=str(evil))

    async def test_pause_sends_rc_command(self, skill):
        s, _ = skill
        s._proc = MagicMock(poll=lambda: None)
        with patch("openocto.skills.media_player.socket.create_connection") as mock_sock:
            mock_conn = MagicMock()
            mock_sock.return_value.__enter__.return_value = mock_conn
            result = await s.execute(action="pause")
            assert "Paused" in result
            mock_conn.sendall.assert_called_once_with(b"pause\n")

    async def test_volume_maps_percent_to_vlc_scale(self, skill):
        s, _ = skill
        s._proc = MagicMock(poll=lambda: None)
        with patch("openocto.skills.media_player.socket.create_connection") as mock_sock:
            mock_conn = MagicMock()
            mock_sock.return_value.__enter__.return_value = mock_conn
            result = await s.execute(action="volume", level=50)
            assert "50%" in result
            sent = mock_conn.sendall.call_args[0][0]
            # 50% -> 128 in VLC's 0..256 scale
            assert sent == b"volume 128\n"

    async def test_volume_clamps(self, skill):
        s, _ = skill
        s._proc = MagicMock(poll=lambda: None)
        with patch("openocto.skills.media_player.socket.create_connection") as mock_sock:
            mock_conn = MagicMock()
            mock_sock.return_value.__enter__.return_value = mock_conn
            await s.execute(action="volume", level=200)
            sent = mock_conn.sendall.call_args[0][0]
            assert sent == b"volume 256\n"

    async def test_seek_relative_forward(self, skill):
        s, _ = skill
        s._proc = MagicMock(poll=lambda: None)
        with patch("openocto.skills.media_player.socket.create_connection") as mock_sock:
            mock_conn = MagicMock()
            mock_sock.return_value.__enter__.return_value = mock_conn
            await s.execute(action="seek", seconds=30)
            sent = mock_conn.sendall.call_args[0][0]
            assert sent == b"seek +30\n"

    async def test_seek_relative_backward(self, skill):
        s, _ = skill
        s._proc = MagicMock(poll=lambda: None)
        with patch("openocto.skills.media_player.socket.create_connection") as mock_sock:
            mock_conn = MagicMock()
            mock_sock.return_value.__enter__.return_value = mock_conn
            await s.execute(action="seek", seconds=-15)
            sent = mock_conn.sendall.call_args[0][0]
            assert sent == b"seek -15\n"

    async def test_fullscreen_toggle(self, skill):
        s, _ = skill
        s._proc = MagicMock(poll=lambda: None)
        with patch("openocto.skills.media_player.socket.create_connection") as mock_sock:
            mock_conn = MagicMock()
            mock_sock.return_value.__enter__.return_value = mock_conn
            await s.execute(action="fullscreen")
            sent = mock_conn.sendall.call_args[0][0]
            assert sent == b"fullscreen\n"

    async def test_status_when_idle(self, skill):
        s, _ = skill
        result = await s.execute(action="status")
        assert "Nothing playing" in result

    async def test_pause_without_vlc_raises(self, skill):
        s, _ = skill
        with pytest.raises(SkillError, match="not running"):
            await s.execute(action="pause")

    async def test_stop_idle_returns_message(self, skill):
        s, _ = skill
        result = await s.execute(action="stop")
        assert "Nothing" in result
