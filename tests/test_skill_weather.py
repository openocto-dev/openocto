"""Tests for the weather skill — mocked HTTP."""

from unittest.mock import MagicMock, patch

import pytest

from openocto.skills.base import SkillError
from openocto.skills.weather import WeatherSkill


class TestWeatherSkill:
    async def test_default_location_required(self):
        s = WeatherSkill()
        with pytest.raises(SkillError, match="No location"):
            await s.execute()

    async def test_uses_explicit_location(self):
        s = WeatherSkill()
        with patch("openocto.skills.weather._fetch_text", return_value="Berlin: ☀ +18°C"):
            result = await s.execute(location="Berlin")
            assert "Berlin" in result

    async def test_uses_default_location_from_config(self):
        s = WeatherSkill({"default_location": "Москва"})
        with patch("openocto.skills.weather._fetch_text") as mock:
            mock.return_value = "Moscow: ❄ -5°C"
            await s.execute()
            url = mock.call_args[0][0]
            assert "Москва" in url or "%D0%9C" in url or "Moscow" in url or "+" in url

    async def test_unknown_location_raises(self):
        s = WeatherSkill({"default_location": "Mars"})
        with patch("openocto.skills.weather._fetch_text", return_value="Unknown location: Mars"):
            with pytest.raises(SkillError, match="Could not find"):
                await s.execute()

    async def test_http_error_raises(self):
        s = WeatherSkill({"default_location": "Berlin"})
        with patch("openocto.skills.weather._fetch_text", side_effect=Exception("network down")):
            with pytest.raises(SkillError, match="lookup failed"):
                await s.execute()

    async def test_detailed_format_uses_more_codes(self):
        s = WeatherSkill({"default_location": "Berlin"})
        with patch("openocto.skills.weather._fetch_text") as mock:
            mock.return_value = "Berlin: ☀ +18°C feels +17°C wind 5km/h"
            await s.execute(detailed=True)
            url = mock.call_args[0][0]
            assert "feels" in url
            assert "wind" in url
            assert "humidity" in url

    async def test_imperial_units(self):
        s = WeatherSkill({"default_location": "NYC", "units": "imperial"})
        with patch("openocto.skills.weather._fetch_text") as mock:
            mock.return_value = "NYC: ☀ +65°F"
            await s.execute()
            url = mock.call_args[0][0]
            assert url.endswith("u")
