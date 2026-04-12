"""Time / date skill — current local time, optional timezone override."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from openocto.skills.base import Skill, SkillError


class _Params(BaseModel):
    timezone: str | None = Field(
        default=None,
        description=(
            "Optional IANA timezone like 'Europe/Moscow' or 'America/New_York'. "
            "Omit to use the host's local time."
        ),
    )
    format: str = Field(
        default="full",
        description="One of: 'full' (date + time), 'time' (clock only), 'date' (date only).",
    )


class TimeSkill(Skill):
    name = "get_current_time"
    description = (
        "Return the current date and/or time. Use whenever the user asks "
        "what time it is, what day it is, what is today's date, or asks "
        "for the time in another city/timezone."
    )
    Parameters = _Params

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._default_tz = (config or {}).get("default_timezone")

    async def execute(self, timezone: str | None = None, format: str = "full") -> str:
        tz_name = timezone or self._default_tz
        now = _now(tz_name)

        if format == "time":
            return now.strftime("%H:%M")
        if format == "date":
            return now.strftime("%A, %B %d, %Y")
        return now.strftime("%A, %B %d, %Y — %H:%M %Z").strip()


def _now(tz_name: str | None) -> datetime:
    if not tz_name:
        return datetime.now().astimezone()
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception as e:
        raise SkillError(f"Unknown timezone {tz_name!r}: {e}")
