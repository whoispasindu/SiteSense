"""Five-day site weather, cached per site so the app works when the provider is down.

The provider is an adapter (``app.integrations.weather``) chosen at startup.

TC-08: when the provider fails, the last cached forecast is returned with ``stale = True`` and a
warning, and nothing crashes.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.logging import get_logger
from app.integrations.weather import DailyWeather, WeatherClient, WeatherUnavailableError
from app.models import Site, WeatherForecast

log = get_logger(__name__)

FORECAST_DAYS = 5
TENTH = Decimal("0.1")

# WMO weather interpretation codes, as used by Open-Meteo.
_WMO: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Showers",
    82: "Violent showers",
    85: "Snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with hail",
}


def describe(code: int | None) -> str:
    return _WMO.get(code, "Unknown") if code is not None else "Unknown"


@dataclass(frozen=True, slots=True)
class Forecast:
    available: bool
    stale: bool
    fetched_at: datetime | None
    message: str | None
    days: list[WeatherForecast]


def _decimal(value: float | None, low: float, high: float) -> Decimal | None:
    if value is None or not low <= value <= high:
        return None
    return Decimal(str(value)).quantize(TENTH)


def _store(db: Session, site: Site, days: list[DailyWeather], now: datetime) -> None:
    for item in days:
        values = {
            "weather_code": item.weather_code,
            "summary": describe(item.weather_code),
            "temp_max_c": _decimal(item.temp_max_c, -60, 70),
            "temp_min_c": _decimal(item.temp_min_c, -60, 70),
            "rain_mm": _decimal(item.rain_mm, 0, 2000),
            "rain_probability": item.rain_probability
            if item.rain_probability is not None and 0 <= item.rain_probability <= 100
            else None,
            "fetched_at": now,
        }
        stmt = insert(WeatherForecast).values(
            id=uuid.uuid4(), site_id=site.id, forecast_date=item.day, **values
        )
        db.execute(stmt.on_conflict_do_update(constraint="uq_weather_forecasts_site_date", set_=values))
    db.commit()


def _cached(db: Session, site: Site, today: date) -> list[WeatherForecast]:
    rows = db.scalars(
        select(WeatherForecast)
        .where(WeatherForecast.site_id == site.id, WeatherForecast.forecast_date >= today)
        .order_by(WeatherForecast.forecast_date)
        .limit(FORECAST_DAYS)
    ).all()
    return list(rows)


def refresh(db: Session, site: Site, client: WeatherClient) -> None:
    """Fetch and cache the forecast. Raises WeatherUnavailableError on any provider failure."""
    if site.latitude is None or site.longitude is None:
        raise WeatherUnavailableError("The site has no coordinates.")
    _store(db, site, client.daily(site.latitude, site.longitude, FORECAST_DAYS), clock.utcnow())


def forecast(db: Session, site: Site, client: WeatherClient, *, cache_hours: int) -> Forecast:
    if site.latitude is None or site.longitude is None:
        return Forecast(
            False, False, None, "Add the site's coordinates (Admin, Sites) to see its weather.", []
        )
    today = clock.site_today()
    cached = _cached(db, site, today)
    oldest = min((row.fetched_at for row in cached), default=None)
    fresh = oldest is not None and clock.utcnow() - oldest < timedelta(hours=cache_hours)
    if fresh and len(cached) >= FORECAST_DAYS:
        return Forecast(True, False, oldest, None, cached)

    try:
        refresh(db, site, client)
    except WeatherUnavailableError as exc:
        log.warning("weather_unavailable", site=site.code, reason=str(exc)[:200])
        if not cached:
            message = "The weather service is unavailable and nothing is cached yet."
            return Forecast(False, True, None, message, [])
        return Forecast(
            True,
            True,
            oldest,
            "The weather service is unavailable. Showing the last saved forecast.",
            cached,
        )
    rows = _cached(db, site, today)
    return Forecast(True, False, min((r.fetched_at for r in rows), default=None), None, rows)


def for_day(db: Session, site_id: uuid.UUID, day: date) -> WeatherForecast | None:
    """The cached forecast for one site and day (used to pre-fill reports)."""
    return db.scalar(
        select(WeatherForecast).where(
            WeatherForecast.site_id == site_id, WeatherForecast.forecast_date == day
        )
    )
