"""File operations skill — list, search, read text files in safe locations.

The user trusts the assistant to look for files like
"найди видео про путешествие" — but we never want it to wander into
``/etc``, ``/root``, dotfiles, or other sensitive paths.  Every operation
runs through ``_resolve()`` which:

1. Expands ``~`` and resolves symlinks.
2. Verifies the resulting path is inside one of the configured
   ``allowed_dirs``.
3. Refuses anything else, even if the LLM tried hard.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from openocto.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED = [
    "~/Videos", "~/Movies", "~/Music", "~/Downloads",
    "~/Documents", "~/Pictures",
]

# A few extensions we'll happily expose by content (small text files only).
_TEXT_EXTS = {".txt", ".md", ".csv", ".log", ".json", ".yaml", ".yml", ".py", ".rst"}
_MAX_READ_BYTES = 64 * 1024  # 64 KB cap for safety
_MAX_LIST_RESULTS = 50


class _Params(BaseModel):
    action: Literal["list", "find", "read"] = Field(
        description=(
            "list = entries in a directory; find = recursive name match "
            "across allowed dirs; read = first 64KB of a text file."
        ),
    )
    path: str | None = Field(
        default=None,
        description="Directory or file path. May start with '~'. Required for list/read.",
    )
    pattern: str | None = Field(
        default=None,
        description="Glob/substring for find (e.g. '*.mp4', 'movie'). Required for find.",
    )
    extension: str | None = Field(
        default=None,
        description="Optional extension filter for list/find (e.g. 'mp4', '.mkv').",
    )


class FileOpsSkill(Skill):
    name = "file_operations"
    description = (
        "List directories, find files by name pattern, or read small text "
        "files. Operates only inside the user's media/document folders for "
        "safety. Use to locate a video, song, or document the user wants "
        "to play, open, or quote from. Returns paths the LLM can pass to "
        "other skills (e.g. play_media)."
    )
    Parameters = _Params

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        raw = (config or {}).get("allowed_dirs") or _DEFAULT_ALLOWED
        self._allowed: list[Path] = []
        for entry in raw:
            try:
                p = Path(entry).expanduser().resolve()
                if p.exists():
                    self._allowed.append(p)
                else:
                    logger.debug("file_ops: skipping missing allowed dir %s", p)
            except Exception:
                logger.debug("file_ops: bad allowed dir %r", entry)
        if not self._allowed:
            # Better to fail loud at init than to silently allow nothing.
            logger.warning("file_ops: no allowed_dirs exist on this host")

    def allowed_dirs(self) -> list[Path]:
        return list(self._allowed)

    def _resolve(self, raw: str) -> Path:
        try:
            p = Path(raw).expanduser().resolve()
        except Exception as e:
            raise SkillError(f"Bad path: {e}")
        for base in self._allowed:
            try:
                p.relative_to(base)
                return p
            except ValueError:
                continue
        raise SkillError(
            f"Path {raw!r} is outside allowed directories: "
            f"{[str(b) for b in self._allowed]}"
        )

    async def execute(
        self,
        action: str,
        path: str | None = None,
        pattern: str | None = None,
        extension: str | None = None,
    ) -> str:
        if action == "list":
            if not path:
                # Default: list the allowed dirs themselves.
                return "\n".join(f"{p}/" for p in self._allowed) or "No allowed dirs configured."
            return self._list(self._resolve(path), extension)

        if action == "find":
            if not pattern:
                raise SkillError("pattern is required for action=find")
            return self._find(pattern, extension)

        if action == "read":
            if not path:
                raise SkillError("path is required for action=read")
            return self._read(self._resolve(path))

        raise SkillError(f"Unknown action: {action}")

    # ── Internal ───────────────────────────────────────────────────────

    def _list(self, dir_path: Path, extension: str | None) -> str:
        if not dir_path.is_dir():
            raise SkillError(f"Not a directory: {dir_path}")
        ext = _normalize_ext(extension)
        entries = []
        for child in sorted(dir_path.iterdir()):
            if child.name.startswith("."):
                continue
            if ext and child.is_file() and child.suffix.lower() != ext:
                continue
            suffix = "/" if child.is_dir() else ""
            entries.append(f"{child.name}{suffix}")
            if len(entries) >= _MAX_LIST_RESULTS:
                entries.append(f"... ({_MAX_LIST_RESULTS}+ entries truncated)")
                break
        return "\n".join(entries) if entries else "(empty)"

    def _find(self, pattern: str, extension: str | None) -> str:
        ext = _normalize_ext(extension)
        needle = pattern.lower()
        # Use glob if user already provided one (contains * or ?), else substring match.
        is_glob = any(c in pattern for c in "*?[")
        results: list[str] = []
        for base in self._allowed:
            try:
                iterator = base.rglob(pattern) if is_glob else base.rglob("*")
            except Exception:
                continue
            for p in iterator:
                if not p.is_file():
                    continue
                if any(part.startswith(".") for part in p.relative_to(base).parts):
                    continue
                if ext and p.suffix.lower() != ext:
                    continue
                if not is_glob and needle not in p.name.lower():
                    continue
                results.append(str(p))
                if len(results) >= _MAX_LIST_RESULTS:
                    break
            if len(results) >= _MAX_LIST_RESULTS:
                break
        if not results:
            return f"No files matching {pattern!r}"
        return "\n".join(results)

    def _read(self, file_path: Path) -> str:
        if not file_path.is_file():
            raise SkillError(f"Not a file: {file_path}")
        if file_path.suffix.lower() not in _TEXT_EXTS:
            raise SkillError(
                f"Refusing to read non-text file ({file_path.suffix}). "
                f"Allowed: {sorted(_TEXT_EXTS)}"
            )
        try:
            with open(file_path, "rb") as f:
                data = f.read(_MAX_READ_BYTES + 1)
        except OSError as e:
            raise SkillError(f"Read failed: {e}")
        truncated = len(data) > _MAX_READ_BYTES
        text = data[:_MAX_READ_BYTES].decode("utf-8", errors="replace")
        if truncated:
            text += f"\n\n[truncated at {_MAX_READ_BYTES} bytes]"
        return text


def _normalize_ext(ext: str | None) -> str | None:
    if not ext:
        return None
    ext = ext.strip().lower()
    if not ext.startswith("."):
        ext = "." + ext
    return ext
