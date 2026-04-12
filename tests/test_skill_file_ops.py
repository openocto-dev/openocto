"""Tests for the file_ops skill — verifies the path allow-list."""

import pytest

from openocto.skills.base import SkillError
from openocto.skills.file_ops import FileOpsSkill


@pytest.fixture
def skill(tmp_path):
    """FileOps with a single tmp dir as the only allowed path."""
    media = tmp_path / "media"
    media.mkdir()
    (media / "movie.mp4").write_bytes(b"fake")
    (media / "song.mp3").write_bytes(b"fake")
    (media / "notes.txt").write_text("hello world\nline 2\n")
    sub = media / "sub"
    sub.mkdir()
    (sub / "deep.mkv").write_bytes(b"fake")
    return FileOpsSkill({"allowed_dirs": [str(media)]}), media


class TestFileOps:
    async def test_list_default_shows_allowed(self, skill):
        s, media = skill
        result = await s.execute(action="list")
        assert str(media) in result

    async def test_list_directory(self, skill):
        s, media = skill
        result = await s.execute(action="list", path=str(media))
        assert "movie.mp4" in result
        assert "notes.txt" in result
        assert "sub/" in result

    async def test_list_with_extension_filter(self, skill):
        s, media = skill
        result = await s.execute(action="list", path=str(media), extension="mp4")
        assert "movie.mp4" in result
        assert "song.mp3" not in result

    async def test_list_outside_allowed_raises(self, skill, tmp_path):
        s, _ = skill
        forbidden = tmp_path / "secret"
        forbidden.mkdir()
        with pytest.raises(SkillError, match="outside allowed"):
            await s.execute(action="list", path=str(forbidden))

    async def test_list_etc_raises(self, skill):
        s, _ = skill
        with pytest.raises(SkillError, match="outside allowed"):
            await s.execute(action="list", path="/etc")

    async def test_find_substring(self, skill):
        s, _ = skill
        result = await s.execute(action="find", pattern="movie")
        assert "movie.mp4" in result

    async def test_find_glob(self, skill):
        s, _ = skill
        result = await s.execute(action="find", pattern="*.mkv")
        assert "deep.mkv" in result

    async def test_find_extension_filter(self, skill):
        s, _ = skill
        result = await s.execute(action="find", pattern="*", extension="mp3")
        assert "song.mp3" in result
        assert "movie.mp4" not in result

    async def test_find_no_results(self, skill):
        s, _ = skill
        result = await s.execute(action="find", pattern="nonexistent")
        assert "No files" in result

    async def test_read_text_file(self, skill):
        s, media = skill
        result = await s.execute(action="read", path=str(media / "notes.txt"))
        assert "hello world" in result

    async def test_read_binary_refused(self, skill):
        s, media = skill
        with pytest.raises(SkillError, match="non-text"):
            await s.execute(action="read", path=str(media / "movie.mp4"))

    async def test_read_outside_allowed_raises(self, skill, tmp_path):
        s, _ = skill
        evil = tmp_path / "evil.txt"
        evil.write_text("secrets")
        with pytest.raises(SkillError, match="outside allowed"):
            await s.execute(action="read", path=str(evil))

    async def test_unknown_action_raises(self, skill):
        s, _ = skill
        with pytest.raises(SkillError):
            await s.execute(action="delete")
