"""Rain climate for the risk model's ``wet_days_ahead`` feature (risk model 1.2, issue #27).

``rain_climate.json`` holds, for seven Sri Lankan towns across the wet, intermediate and dry zones,
the share of days with heavy rain (10 mm or more, BR-06) in each calendar month, from real
Open-Meteo history (2012 to 2025). It is written by ``ml/data_generator/climate.py`` from the same
data the simulator uses, and an ML test checks the two agree.

Which climate a site uses (``for_site``):

1. A site in Sri Lanka: the nearest of the seven towns, as the model was trained.
2. A site elsewhere: its own climate, worked out the same way from its own coordinates' history
   (``services/rain_climate.py`` fetches it once and stores it on the site).
3. Otherwise (no coordinates, or the history not fetched yet): the seven towns' average, with a note.

Scoring never fetches anything: it reads this file and what is stored on the site.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from pathlib import Path

CLIMATE_FILE = Path(__file__).with_name("rain_climate.json")
HEAVY_RAIN_MM = 10.0  # BR-06
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
    """Every town's climate averaged: used when a site has no climate of its own."""
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


# Sri Lanka's bounding box, which no other country's land reaches (India's nearest point,
# Dhanushkodi, lies west of it).
SRI_LANKA = (5.85, 9.9, 79.5, 81.95)  # latitude from, to; longitude from, to
START, END = "2012-01-01", "2025-12-31"  # the history the towns' climates come from
OWN_CLIMATE = "own"


@dataclass(frozen=True, slots=True)
class Choice:
    town: Town
    note: str | None = None


def in_sri_lanka(latitude: float, longitude: float) -> bool:
    lat_from, lat_to, lon_from, lon_to = SRI_LANKA
    return lat_from <= latitude <= lat_to and lon_from <= longitude <= lon_to


def needs_own(latitude: float | None, longitude: float | None) -> bool:
    """Whether a site needs its own climate fetched: it has coordinates outside Sri Lanka."""
    return latitude is not None and longitude is not None and not in_sri_lanka(latitude, longitude)


def own(shares: list[float] | tuple[float, ...]) -> Town:
    if len(shares) != 12 or not all(math.isfinite(v) and 0 <= v <= 1 for v in shares):
        raise ClimateError("A site's climate needs 12 monthly shares between 0 and 1")
    return Town(OWN_CLIMATE, 0.0, 0.0, tuple(float(v) for v in shares))


def for_site(latitude: float | None, longitude: float | None, shares: list[float] | None) -> Choice:
    """The climate the risk and supplier models use for a site (see the module docstring)."""
    average = "the average of the seven Sri Lankan towns the model was trained on"
    if latitude is None or longitude is None:
        return Choice(national_average(), f"The site has no coordinates: rain ahead uses {average}.")
    if in_sri_lanka(latitude, longitude):
        return Choice(nearest(latitude, longitude).town)
    if shares is not None:
        try:
            return Choice(own(shares))
        except ClimateError:
            pass
    return Choice(
        national_average(),
        f"The site's rain history has not been fetched yet (it is, with the next weather refresh): "
        f"rain ahead uses {average}.",
    )


def heavy_day_shares(days: list[date], rain_mm: list[float | None]) -> tuple[float, ...]:
    """Share of days with heavy rain (10 mm or more) per calendar month, January first.

    The same sums as ``heavy_rain_climate`` in ml/data_generator/simulate.py: a day with no value
    counts as dry (as the training data's download does), and shares are rounded to 4 decimals.
    """
    heavy = [0] * 12
    total = [0] * 12
    for day, mm in zip(days, rain_mm, strict=True):
        total[day.month - 1] += 1
        heavy[day.month - 1] += int(mm is not None and mm >= HEAVY_RAIN_MM)
    if not all(total):
        raise ClimateError("The rain history does not cover every month")
    return tuple(round(heavy[m] / total[m], 4) for m in range(12))
