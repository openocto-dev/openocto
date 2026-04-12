"""Launcher skill — open URLs and run whitelisted applications.

The whitelist is mandatory for ``launch_app``: only commands explicitly
listed in config (default: a small safe set) can be spawned.  URLs go
through the platform's standard "open" command (``xdg-open`` on Linux,
``open`` on macOS, ``start`` on Windows).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from typing import Any, Literal

from pydantic import BaseModel, Field

from openocto.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_APPS = ["firefox", "chromium", "chromium-browser", "code", "xdg-open"]
# vlc/mpv intentionally excluded — use the media_player skill instead so
# playback can be controlled (pause/stop/seek). Whitelisting them here would
# make the LLM pick this generic launcher and lose all playback control.


class _Params(BaseModel):
    action: Literal["launch_app", "open_url"] = Field(
        description="launch_app = run a whitelisted CLI/GUI app; open_url = open URL in default browser.",
    )
    name: str | None = Field(
        default=None,
        description="App name (must be in the configured whitelist). Required for launch_app.",
    )
    args: list[str] | None = Field(
        default=None,
        description="Optional arguments to pass to the app (e.g. a file path).",
    )
    url: str | None = Field(
        default=None,
        description="URL to open. Required for open_url.",
    )


class LauncherSkill(Skill):
    name = "launch_app_or_url"
    description = (
        "Launch a non-media desktop application (browser, code editor) or "
        "open a URL in the user's default browser. Use when the user says "
        "'open Firefox', 'open the website', 'launch the editor'. "
        "DO NOT use this for video or audio playback — use the media_player "
        "skill instead so playback can be controlled. "
        "Apps must be in the safety whitelist; URLs must use http/https."
    )
    Parameters = _Params

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._allowed = list((config or {}).get("allowed_apps") or _DEFAULT_ALLOWED_APPS)

    async def execute(
        self,
        action: str,
        name: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
    ) -> str:
        if action == "launch_app":
            if not name:
                raise SkillError("name is required for launch_app")
            return self._launch_app(name, args or [])
        if action == "open_url":
            if not url:
                raise SkillError("url is required for open_url")
            return self._open_url(url)
        raise SkillError(f"Unknown action: {action}")

    def _launch_app(self, name: str, args: list[str]) -> str:
        if name not in self._allowed:
            raise SkillError(
                f"App {name!r} not in whitelist. Allowed: {self._allowed}. "
                f"Add it under skills.launcher.allowed_apps if you trust it."
            )
        binary = shutil.which(name)
        if not binary:
            raise SkillError(f"App {name!r} is whitelisted but not installed on PATH")
        try:
            proc = subprocess.Popen(
                [binary, *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as e:
            raise SkillError(f"Failed to launch {name}: {e}")
        return f"Launched {name} (pid={proc.pid})"

    def _open_url(self, url: str) -> str:
        if not (url.startswith("http://") or url.startswith("https://")):
            raise SkillError("Only http(s) URLs are allowed")
        opener = _platform_opener()
        if opener is None:
            raise SkillError("No URL opener found on this platform")
        try:
            subprocess.Popen(
                [*opener, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as e:
            raise SkillError(f"Failed to open URL: {e}")
        return f"Opened {url}"


def _platform_opener() -> list[str] | None:
    if sys.platform == "darwin":
        return ["open"]
    if sys.platform.startswith("linux"):
        if shutil.which("xdg-open"):
            return ["xdg-open"]
        return None
    if sys.platform.startswith("win"):
        return ["cmd", "/c", "start", ""]
    return None
