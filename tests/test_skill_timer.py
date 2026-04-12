"""Tests for the timer skill — duration parsing, lifecycle, cancellation."""

import asyncio

import pytest

from openocto.skills.base import SkillError
from openocto.skills.timer import TimerSkill, _parse_duration


class TestDurationParser:
    def test_seconds(self):
        assert _parse_duration("30s").total_seconds() == 30
        assert _parse_duration("45 seconds").total_seconds() == 45

    def test_minutes(self):
        assert _parse_duration("5m").total_seconds() == 300
        assert _parse_duration("2 minutes").total_seconds() == 120

    def test_hours(self):
        assert _parse_duration("1h").total_seconds() == 3600
        assert _parse_duration("2 hours").total_seconds() == 7200

    def test_compound(self):
        assert _parse_duration("1h30m").total_seconds() == 5400
        assert _parse_duration("2h15m30s").total_seconds() == 8130

    def test_invalid_raises(self):
        with pytest.raises(SkillError):
            _parse_duration("soon")


class TestTimerSkill:
    async def test_set_short_timer_fires(self):
        skill = TimerSkill()
        result = await skill.execute(action="set", duration="1s", label="test")
        assert "Timer #1 set" in result

        # Wait for fire
        await asyncio.sleep(1.3)

        listed = await skill.execute(action="list")
        assert "No active timers" in listed

    async def test_list_empty(self):
        skill = TimerSkill()
        result = await skill.execute(action="list")
        assert "No active timers" in result

    async def test_set_and_cancel(self):
        skill = TimerSkill()
        await skill.execute(action="set", duration="60s", label="long")
        listed = await skill.execute(action="list")
        assert "long" in listed

        cancelled = await skill.execute(action="cancel", timer_id=1)
        assert "Cancelled" in cancelled

        listed = await skill.execute(action="list")
        assert "No active timers" in listed

    async def test_cancel_unknown_raises(self):
        skill = TimerSkill()
        with pytest.raises(SkillError):
            await skill.execute(action="cancel", timer_id=99)

    async def test_set_requires_duration(self):
        skill = TimerSkill()
        with pytest.raises(SkillError):
            await skill.execute(action="set")

    async def test_multiple_timers(self):
        skill = TimerSkill()
        await skill.execute(action="set", duration="60s", label="a")
        await skill.execute(action="set", duration="60s", label="b")
        listed = await skill.execute(action="list")
        assert "a" in listed
        assert "b" in listed
        # cleanup
        await skill.execute(action="cancel", timer_id=1)
        await skill.execute(action="cancel", timer_id=2)
