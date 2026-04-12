"""Timer / alarm skill — in-process scheduled callbacks.

Timers fire after a relative duration; alarms (set + cancel + list) all
go through the same internal store keyed by id.  When a timer fires we
print a message and try to play a beep through the bound AudioPlayer +
speak the label via the bound TTS engine.

Persistence is intentionally NOT implemented in this iteration —
restarting the process clears scheduled timers.  A future revision can
move the store into SQLite.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from openocto.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)


@dataclass
class _Timer:
    id: int
    label: str
    fire_at: datetime
    task: asyncio.Task | None = field(default=None, repr=False)


class _Params(BaseModel):
    action: Literal["set", "list", "cancel"] = Field(
        description="set = create a new timer; list = show active; cancel = remove by id.",
    )
    duration: str | None = Field(
        default=None,
        description=(
            "Duration like '5m', '1h30m', '45s', '2 minutes', '1 hour'. "
            "Required for action=set."
        ),
    )
    label: str = Field(
        default="Timer",
        description="What the timer is for (e.g. 'pasta', 'standup'). Spoken when it fires.",
    )
    timer_id: int | None = Field(
        default=None,
        description="Timer id to cancel (only for action=cancel).",
    )


_DUR_RE = re.compile(
    r"(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|s|m|h)",
    re.IGNORECASE,
)


def _parse_duration(text: str) -> timedelta:
    """Parse '1h30m', '5 minutes', '45s' into a timedelta."""
    total = 0
    for match in _DUR_RE.finditer(text):
        n = int(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("s"):
            total += n
        elif unit.startswith("m") and not unit.startswith("mo"):
            total += n * 60
        elif unit.startswith("h"):
            total += n * 3600
    if total == 0:
        raise SkillError(f"Could not parse duration: {text!r}")
    return timedelta(seconds=total)


def _format_remaining(td: timedelta) -> str:
    secs = max(0, int(td.total_seconds()))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


class TimerSkill(Skill):
    name = "manage_timers"
    description = (
        "Set, list, or cancel timers and short alarms. Use when the user "
        "says 'set a timer for X', 'wake me in N minutes', 'cancel the "
        "pasta timer', 'how long left on my timer'. Timers are in-memory "
        "and lost on restart — say so if the user asks for tomorrow."
    )
    Parameters = _Params

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._timers: dict[int, _Timer] = {}
        self._next_id = 1
        # Bound by registry.bind_context(...) — used to fire announcements.
        self._ctx_player = None
        self._ctx_loop = None

    async def execute(
        self,
        action: str,
        duration: str | None = None,
        label: str = "Timer",
        timer_id: int | None = None,
    ) -> str:
        if action == "set":
            if not duration:
                raise SkillError("duration is required for action=set")
            delta = _parse_duration(duration)
            return self._set(delta, label)

        if action == "list":
            return self._list()

        if action == "cancel":
            if timer_id is None:
                raise SkillError("timer_id is required for action=cancel")
            return self._cancel(timer_id)

        raise SkillError(f"Unknown action: {action}")

    # ── Internal ───────────────────────────────────────────────────────

    def _set(self, delta: timedelta, label: str) -> str:
        tid = self._next_id
        self._next_id += 1
        fire_at = datetime.now().astimezone() + delta
        timer = _Timer(id=tid, label=label, fire_at=fire_at)
        loop = self._ctx_loop or asyncio.get_event_loop()
        timer.task = loop.create_task(self._wait_and_fire(timer))
        self._timers[tid] = timer
        return (
            f"Timer #{tid} set: {label!r} in {_format_remaining(delta)} "
            f"(fires at {fire_at.strftime('%H:%M:%S')})"
        )

    def _list(self) -> str:
        if not self._timers:
            return "No active timers."
        now = datetime.now().astimezone()
        lines = []
        for t in sorted(self._timers.values(), key=lambda x: x.fire_at):
            lines.append(f"#{t.id}: {t.label} — {_format_remaining(t.fire_at - now)} left")
        return "\n".join(lines)

    def _cancel(self, tid: int) -> str:
        timer = self._timers.pop(tid, None)
        if timer is None:
            raise SkillError(f"No timer #{tid}")
        if timer.task and not timer.task.done():
            timer.task.cancel()
        return f"Cancelled timer #{tid} ({timer.label})"

    async def _wait_and_fire(self, timer: _Timer) -> None:
        try:
            seconds = (timer.fire_at - datetime.now().astimezone()).total_seconds()
            if seconds > 0:
                await asyncio.sleep(seconds)
            await self._fire(timer)
        except asyncio.CancelledError:
            pass
        finally:
            self._timers.pop(timer.id, None)

    async def _fire(self, timer: _Timer) -> None:
        msg = f"⏰ Timer: {timer.label}"
        print(f"\n{msg}")
        player = self._ctx_player
        if player is not None:
            try:
                # Three short beeps so it's audible above ambient noise.
                player.beep(freq=880.0, duration=0.18)
                await asyncio.sleep(0.22)
                player.beep(freq=880.0, duration=0.18)
                await asyncio.sleep(0.22)
                player.beep(freq=880.0, duration=0.18)
            except Exception:
                logger.debug("Timer beep failed", exc_info=True)
