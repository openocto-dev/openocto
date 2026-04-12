"""Media player skill — control VLC for video/audio playback.

Spawns a long-lived VLC process with its **RC interface** bound to a
local TCP port, then sends text commands ("pause", "stop", "seek +30",
"volume 50") over that socket.  This avoids the libvlc Python bindings
(which are heavy and version-fragile) and works on any host where the
``vlc`` binary is on PATH.

Files passed to ``play`` go through the bound FileOpsSkill so the same
allow-list applies — the LLM can't hand VLC ``/etc/passwd``.

Lifecycle:
  * ``play`` — kills any previous instance, starts VLC fullscreen with
    the given file (or just plays/resumes if no file).
  * ``pause`` / ``toggle_pause`` — sends ``pause``.
  * ``stop`` — ``stop`` over RC, then ``terminate()`` after a short grace.
  * ``seek`` — ``seek +N`` / ``seek -N`` / ``seek N`` (absolute seconds).
  * ``volume`` — ``volume <0..256>`` (mapped from 0..100 for the LLM).
  * ``fullscreen`` — toggle.
  * ``status`` — query is best-effort; returns 'playing' or 'unknown'.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from openocto.skills.base import Skill, SkillError, SkillUnavailable
from openocto.skills.file_ops import FileOpsSkill

logger = logging.getLogger(__name__)

_DEFAULT_RC_PORT = 9919
_RC_HOST = "127.0.0.1"
_RC_TIMEOUT = 1.5
_STARTUP_DELAY = 0.4  # seconds before first RC command after launch


class _Params(BaseModel):
    action: Literal[
        "play", "pause", "toggle_pause", "stop", "seek",
        "volume", "fullscreen", "status",
    ] = Field(description="What to do with the video player.")
    file: str | None = Field(
        default=None,
        description=(
            "Absolute path or path inside an allowed media directory. "
            "Only used for action=play. If omitted on play, resumes current."
        ),
    )
    seconds: int | None = Field(
        default=None,
        description=(
            "For seek: relative seconds (positive=forward, negative=back) "
            "or absolute if greater than 1000."
        ),
    )
    level: int | None = Field(
        default=None,
        description="For volume: 0..100. Maps internally to VLC's 0..256 scale.",
    )


class MediaPlayerSkill(Skill):
    name = "media_player"
    description = (
        "Control video and audio playback in VLC. Use when the user wants "
        "to play a movie, pause/resume, stop, seek forward/back, change "
        "volume, or toggle fullscreen. Pair with file_operations to find "
        "the file first if the user names a movie without giving a path. "
        "Only one VLC instance is managed at a time — playing a new file "
        "replaces the old one."
    )
    Parameters = _Params

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        cfg = config or {}
        self._binary = _find_vlc(cfg.get("binary"))
        if not self._binary:
            raise SkillUnavailable(
                "vlc binary not found on PATH. Install: apt install vlc / brew install vlc"
            )
        self._rc_port = int(cfg.get("rc_port", _DEFAULT_RC_PORT))
        self._fullscreen_default = bool(cfg.get("fullscreen_default", True))
        self._proc: subprocess.Popen | None = None
        self._current_file: Path | None = None
        # Bound by the registry from the OpenOctoApp's FileOpsSkill instance.
        self._ctx_file_ops: FileOpsSkill | None = None

    async def execute(
        self,
        action: str,
        file: str | None = None,
        seconds: int | None = None,
        level: int | None = None,
    ) -> str:
        if action == "play":
            return await self._play(file)
        if action == "pause":
            self._send("pause")
            return "Paused"
        if action == "toggle_pause":
            self._send("pause")
            return "Toggled pause"
        if action == "stop":
            return self._stop()
        if action == "seek":
            return self._seek(seconds)
        if action == "volume":
            return self._volume(level)
        if action == "fullscreen":
            self._send("fullscreen")
            return "Toggled fullscreen"
        if action == "status":
            return self._status()
        raise SkillError(f"Unknown action: {action}")

    # ── Internal ───────────────────────────────────────────────────────

    async def _play(self, file: str | None) -> str:
        # No file given — assume the user wants resume on the current process.
        if not file:
            if self._proc and self._proc.poll() is None:
                self._send("play")
                return "Resumed playback"
            raise SkillError("Nothing to resume — pass a file path or use file_operations to find one.")

        path = self._validate_file(file)
        # Replace any existing VLC.
        self._stop(quiet=True)

        cmd = [
            self._binary,
            "--intf", "dummy",
            "--extraintf", "rc",
            "--rc-host", f"{_RC_HOST}:{self._rc_port}",
            "--no-video-title-show",
        ]
        if self._fullscreen_default:
            cmd.append("--fullscreen")
        cmd.append(str(path))

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as e:
            raise SkillError(f"Failed to launch VLC: {e}")

        self._current_file = path
        # Give VLC a moment to bind the RC socket before any follow-up commands.
        await asyncio.sleep(_STARTUP_DELAY)
        return f"Playing {path.name}"

    def _stop(self, quiet: bool = False) -> str:
        if not self._proc or self._proc.poll() is not None:
            self._proc = None
            self._current_file = None
            if quiet:
                return ""
            return "Nothing playing"
        try:
            self._send("quit", swallow=True)
        except Exception:
            pass
        # Grace period for clean shutdown, then SIGTERM.
        deadline = time.time() + 1.5
        while time.time() < deadline and self._proc.poll() is None:
            time.sleep(0.05)
        if self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None
        prev = self._current_file
        self._current_file = None
        return f"Stopped{' ' + prev.name if prev else ''}"

    def _seek(self, seconds: int | None) -> str:
        if seconds is None:
            raise SkillError("seek requires 'seconds'")
        if abs(seconds) >= 1000:
            self._send(f"seek {abs(seconds)}")
            return f"Seek to {seconds}s (absolute)"
        sign = "+" if seconds >= 0 else "-"
        # VLC RC accepts "seek +30" / "seek -10" with the leading sign.
        self._send(f"seek {sign}{abs(seconds)}")
        return f"Seek {sign}{abs(seconds)}s"

    def _volume(self, level: int | None) -> str:
        if level is None:
            raise SkillError("volume requires 'level' (0..100)")
        level = max(0, min(100, int(level)))
        # VLC RC volume range is 0..256 by default.
        vlc_level = int(round(level * 256 / 100))
        self._send(f"volume {vlc_level}")
        return f"Volume set to {level}%"

    def _status(self) -> str:
        if not self._proc or self._proc.poll() is not None:
            return "Nothing playing"
        return f"Playing: {self._current_file.name if self._current_file else 'unknown'}"

    def _send(self, cmd: str, swallow: bool = False) -> None:
        if not self._proc or self._proc.poll() is not None:
            if swallow:
                return
            raise SkillError("VLC is not running — call action=play first")
        try:
            with socket.create_connection((_RC_HOST, self._rc_port), timeout=_RC_TIMEOUT) as sock:
                sock.sendall((cmd + "\n").encode("utf-8"))
        except OSError as e:
            if swallow:
                return
            raise SkillError(f"VLC RC connection failed: {e}")

    def _validate_file(self, raw: str) -> Path:
        path = Path(raw).expanduser()
        if self._ctx_file_ops is not None:
            # Reuse FileOps's allow-list so we can't be tricked into /etc.
            return self._ctx_file_ops._resolve(str(path))
        # Without bound FileOps, fall back to a permissive resolve but still
        # require an absolute existing file.
        path = path.resolve()
        if not path.exists():
            raise SkillError(f"File not found: {path}")
        return path

    def shutdown(self) -> None:
        """Called by app cleanup to ensure no orphan VLC."""
        self._stop(quiet=True)


def _find_vlc(override: str | None) -> str | None:
    if override:
        return override if Path(override).exists() else shutil.which(override)
    found = shutil.which("vlc")
    if found:
        return found
    if sys.platform == "darwin":
        candidate = "/Applications/VLC.app/Contents/MacOS/VLC"
        if Path(candidate).exists():
            return candidate
    return None
