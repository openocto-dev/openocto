"""Tests for the pure-Python skills (no network, no subprocess)."""

import pytest

from openocto.skills.base import SkillError
from openocto.skills.time_skill import TimeSkill
from openocto.skills.unit_converter import UnitConverterSkill


class TestTimeSkill:
    async def test_full_format(self):
        skill = TimeSkill()
        result = await skill.execute()
        assert ":" in result  # has clock
        assert any(c.isalpha() for c in result)  # has weekday/month name

    async def test_time_only_format(self):
        skill = TimeSkill()
        result = await skill.execute(format="time")
        assert len(result) == 5  # HH:MM
        assert result[2] == ":"

    async def test_date_only_format(self):
        skill = TimeSkill()
        result = await skill.execute(format="date")
        assert ":" not in result

    async def test_explicit_timezone(self):
        skill = TimeSkill()
        result = await skill.execute(timezone="UTC", format="time")
        assert len(result) == 5

    async def test_unknown_timezone_raises(self):
        skill = TimeSkill()
        with pytest.raises(SkillError):
            await skill.execute(timezone="Mars/Olympus")

    async def test_default_timezone_from_config(self):
        skill = TimeSkill({"default_timezone": "UTC"})
        result = await skill.execute(format="time")
        assert len(result) == 5


class TestUnitConverter:
    @pytest.fixture
    def skill(self):
        return UnitConverterSkill()

    async def test_kg_to_lb(self, skill):
        result = await skill.execute(value=1.0, from_unit="kg", to_unit="lb")
        assert "2.2" in result
        assert "weight" in result

    async def test_km_to_miles(self, skill):
        result = await skill.execute(value=10.0, from_unit="km", to_unit="mi")
        assert "6.21" in result or "6.2" in result

    async def test_celsius_to_fahrenheit(self, skill):
        result = await skill.execute(value=100.0, from_unit="celsius", to_unit="fahrenheit")
        assert "212" in result

    async def test_fahrenheit_to_celsius(self, skill):
        result = await skill.execute(value=32.0, from_unit="f", to_unit="c")
        assert "0" in result

    async def test_liters_to_gallons(self, skill):
        result = await skill.execute(value=10.0, from_unit="l", to_unit="gal")
        assert "2.6" in result

    async def test_meters_to_feet(self, skill):
        result = await skill.execute(value=1.0, from_unit="m", to_unit="ft")
        assert "3.28" in result

    async def test_unknown_unit_raises(self, skill):
        with pytest.raises(SkillError):
            await skill.execute(value=1.0, from_unit="parsec", to_unit="m")

    async def test_cross_family_raises(self, skill):
        with pytest.raises(SkillError):
            await skill.execute(value=1.0, from_unit="kg", to_unit="m")

    async def test_case_insensitive(self, skill):
        result = await skill.execute(value=1.0, from_unit="KG", to_unit="LB")
        assert "2.2" in result
