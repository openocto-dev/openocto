"""Unit converter skill — common length, weight, volume, temperature.

Deliberately small (no `pint` dependency).  Each unit lives in a
"family" with a base unit; conversion is just a multiply (and an
offset for temperature).
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from openocto.skills.base import Skill, SkillError


# family -> {alias: (base_factor, base_offset)}
_FAMILIES: dict[str, dict[str, tuple[float, float]]] = {
    "length": {
        "m": (1.0, 0.0), "meter": (1.0, 0.0), "meters": (1.0, 0.0),
        "km": (1000.0, 0.0), "kilometer": (1000.0, 0.0), "kilometers": (1000.0, 0.0),
        "cm": (0.01, 0.0), "centimeter": (0.01, 0.0), "centimeters": (0.01, 0.0),
        "mm": (0.001, 0.0), "millimeter": (0.001, 0.0), "millimeters": (0.001, 0.0),
        "mi": (1609.344, 0.0), "mile": (1609.344, 0.0), "miles": (1609.344, 0.0),
        "yd": (0.9144, 0.0), "yard": (0.9144, 0.0), "yards": (0.9144, 0.0),
        "ft": (0.3048, 0.0), "foot": (0.3048, 0.0), "feet": (0.3048, 0.0),
        "in": (0.0254, 0.0), "inch": (0.0254, 0.0), "inches": (0.0254, 0.0),
    },
    "weight": {
        "kg": (1.0, 0.0), "kilogram": (1.0, 0.0), "kilograms": (1.0, 0.0),
        "g": (0.001, 0.0), "gram": (0.001, 0.0), "grams": (0.001, 0.0),
        "mg": (1e-6, 0.0), "milligram": (1e-6, 0.0), "milligrams": (1e-6, 0.0),
        "lb": (0.45359237, 0.0), "pound": (0.45359237, 0.0), "pounds": (0.45359237, 0.0),
        "oz": (0.028349523125, 0.0), "ounce": (0.028349523125, 0.0), "ounces": (0.028349523125, 0.0),
        "t": (1000.0, 0.0), "ton": (1000.0, 0.0), "tonne": (1000.0, 0.0), "tonnes": (1000.0, 0.0),
    },
    "volume": {
        "l": (1.0, 0.0), "liter": (1.0, 0.0), "liters": (1.0, 0.0), "litre": (1.0, 0.0),
        "ml": (0.001, 0.0), "milliliter": (0.001, 0.0), "milliliters": (0.001, 0.0),
        "gal": (3.785411784, 0.0), "gallon": (3.785411784, 0.0), "gallons": (3.785411784, 0.0),
        "qt": (0.946352946, 0.0), "quart": (0.946352946, 0.0), "quarts": (0.946352946, 0.0),
        "pt": (0.473176473, 0.0), "pint": (0.473176473, 0.0), "pints": (0.473176473, 0.0),
        "cup": (0.236588236, 0.0), "cups": (0.236588236, 0.0),
    },
    # Temperature uses offsets — base unit is Celsius.
    "temperature": {
        "c": (1.0, 0.0), "celsius": (1.0, 0.0),
        "f": (5.0 / 9.0, -32.0 * 5.0 / 9.0), "fahrenheit": (5.0 / 9.0, -32.0 * 5.0 / 9.0),
        "k": (1.0, -273.15), "kelvin": (1.0, -273.15),
    },
}


def _normalize(unit: str) -> str:
    return unit.strip().lower().rstrip(".")


def _find_family(unit: str) -> tuple[str, tuple[float, float]] | None:
    u = _normalize(unit)
    for family, table in _FAMILIES.items():
        if u in table:
            return family, table[u]
    return None


def _convert(value: float, from_unit: str, to_unit: str) -> tuple[float, str]:
    fa = _find_family(from_unit)
    fb = _find_family(to_unit)
    if not fa:
        raise SkillError(f"Unknown unit: {from_unit!r}")
    if not fb:
        raise SkillError(f"Unknown unit: {to_unit!r}")
    if fa[0] != fb[0]:
        raise SkillError(
            f"Cannot convert {fa[0]} → {fb[0]} ({from_unit} to {to_unit})"
        )
    family = fa[0]

    if family == "temperature":
        # value -> celsius -> target
        f_factor, f_offset = fa[1]
        t_factor, t_offset = fb[1]
        celsius = value * f_factor + f_offset
        result = (celsius - t_offset) / t_factor
    else:
        # multiplicative
        f_factor = fa[1][0]
        t_factor = fb[1][0]
        base = value * f_factor
        result = base / t_factor

    return result, family


class _Params(BaseModel):
    value: float = Field(description="Numeric quantity to convert.")
    from_unit: str = Field(description="Source unit (e.g. 'kg', 'celsius', 'mile').")
    to_unit: str = Field(description="Target unit (e.g. 'lb', 'fahrenheit', 'km').")


class UnitConverterSkill(Skill):
    name = "convert_units"
    description = (
        "Convert a numeric value between units of length, weight, volume, "
        "or temperature. Use when the user asks 'how many X in Y' or "
        "'convert N units to other units'."
    )
    Parameters = _Params

    async def execute(self, value: float, from_unit: str, to_unit: str) -> str:
        result, family = _convert(value, from_unit, to_unit)
        # Round sanely: 4 sig figs is enough for spoken responses.
        if abs(result) >= 100:
            formatted = f"{result:.1f}"
        elif abs(result) >= 1:
            formatted = f"{result:.2f}"
        else:
            formatted = f"{result:.4f}"
        formatted = formatted.rstrip("0").rstrip(".")
        return f"{value} {from_unit} = {formatted} {to_unit} ({family})"
