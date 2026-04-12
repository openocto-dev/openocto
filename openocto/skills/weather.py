"""Weather skill — wttr.in (no API key required).

Format codes:
  %l = location, %c = condition emoji, %t = temperature,
  %f = feels-like, %w = wind, %h = humidity, %p = precipitation
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from openocto.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)

_BASE_URL = "https://wttr.in"
_TIMEOUT = 8.0


class _Params(BaseModel):
    location: str | None = Field(
        default=None,
        description=(
            "City, region, airport code, or coordinates. "
            "Omit to use the configured default location."
        ),
    )
    detailed: bool = Field(
        default=False,
        description="If true, include feels-like, wind, and humidity.",
    )


class WeatherSkill(Skill):
    name = "get_weather"
    description = (
        "Get current weather conditions for a city or location via wttr.in. "
        "Use when the user asks about weather, temperature, or asks if it "
        "will rain. NOT for: historical weather, forecasts more than 3 days "
        "out, or severe weather alerts."
    )
    Parameters = _Params

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._default_location = (config or {}).get("default_location")
        self._units = (config or {}).get("units", "metric")  # metric | imperial

    async def execute(self, location: str | None = None, detailed: bool = False) -> str:
        loc = (location or self._default_location or "").strip()
        if not loc:
            raise SkillError(
                "No location provided and no default_location configured. "
                "Ask the user where they want the weather for."
            )

        fmt = (
            "%l: %c %t (feels like %f), wind %w, humidity %h, %p precipitation"
            if detailed
            else "%l: %c %t"
        )
        unit_char = "m" if self._units == "metric" else "u"
        # wttr.in URL format: /<location>?format=<spec>&<unit>
        path = loc.replace(" ", "+")
        url = f"{_BASE_URL}/{path}?format={fmt}&{unit_char}"

        try:
            text = await asyncio.to_thread(_fetch_text, url)
        except Exception as e:
            raise SkillError(f"Weather lookup failed: {e}")

        if not text or text.lower().startswith("unknown location"):
            raise SkillError(f"Could not find weather for {loc!r}")
        return text


def _fetch_text(url: str) -> str:
    """Synchronous HTTP GET — runs in a worker thread."""
    import requests

    response = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "curl/8"})
    response.raise_for_status()
    return response.text.strip()
