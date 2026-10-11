"""Rain climate for the risk model's ``wet_days_ahead`` feature (risk model 1.2, issue #27).

``rain_climate.json`` holds, for seven Sri Lankan towns across the wet, intermediate and dry zones,
the share of days with heavy rain (10 mm or more, BR-06) in each calendar month, from real
Open-Meteo history (2012 to 2025). It is written by ``ml/data_generator/climate.py`` from the same
data the simulator uses, and an ML test checks the two agree. A site uses its nearest town.

It is local data: nothing is fetched to compute the feature. The file is validated before use.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from pathlib import Path

CLIMATE_FILE = Path(__file__).with_name("rain_climate.json")
WORKING_DAYS = 6  # Monday to Saturday, as in the simulator the model was trained on
MIN_DAYS_AHEAD = 28  # past the planned end, still look at the next four weeks
EARTH_RADIUS_KM = 6371.0


class ClimateError(ValueError):
    """The climate file is missing or not valid."""


@dataclass(frozen=True, slots=True)
class Town:
    name: str
    latitude: float
    longitude: float
    heavy_day_share: tuple[float, ...]  # January to December


@dataclass(frozen=True, slots=True)
class Nearest:
    town: Town
    distance_km: float


def _town(name: str, raw: object) -> Town:
    if not isinstance(raw, dict):
        raise ClimateError(f"{name}: not an object")
    lat, lon, shares = raw.get("latitude"), raw.get("longitude"), raw.get("heavy_day_share_by_month")
    if not isinstance(lat, int | float) or not isinstance(lon, int | float):
        raise ClimateError(f"{name}: bad coordinates")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ClimateError(f"{name}: bad coordinates")
    if (
        not isinstance(shares, list)
        or len(shares) != 12
        or not all(isinstance(v, int | float) and math.isfinite(v) and 0 <= v <= 1 for v in shares)
    ):
        raise ClimateError(f"{name}: needs 12 monthly shares between 0 and 1")
    return Town(name, float(lat), float(lon), tuple(float(v) for v in shares))


@cache
def towns(path: Path = CLIMATE_FILE) -> tuple[Town, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClimateError(f"Cannot read the climate file: {exc}") from exc
    entries = raw.get("towns") if isinstance(raw, dict) else None
    if not isinstance(entries, dict) or not 1 <= len(entries) <= 100:
        raise ClimateError("The climate file needs between 1 and 100 towns")
    return tuple(_town(str(name), value) for name, value in sorted(entries.items()))


def national_average() -> Town:
    """Every town's climate averaged: used when a site has no coordinates."""
    all_towns = towns()
    shares = tuple(sum(t.heavy_day_share[m] for t in all_towns) / len(all_towns) for m in range(12))
    return Town("Sri Lanka average", 0.0, 0.0, shares)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def nearest(latitude: float, longitude: float) -> Nearest:
    return min(
        (Nearest(t, _distance_km(latitude, longitude, t.latitude, t.longitude)) for t in towns()),
        key=lambda n: n.distance_km,
    )


def wet_days_ahead(town: Town, today: date, planned_end: date) -> float:
    """Heavy-rain working days (Mon to Sat) expected from tomorrow to the planned end, from the climate.

    Never less than the next 28 days. Mirrors ``wet_days_ahead`` in ml/data_generator/simulate.py.
    """
    last = max(planned_end, today + timedelta(days=MIN_DAYS_AHEAD))
    total = 0.0
    day = today + timedelta(days=1)
    while day <= last:
        if day.weekday() < WORKING_DAYS:
            total += town.heavy_day_share[day.month - 1]
        day += timedelta(days=1)
    return total
