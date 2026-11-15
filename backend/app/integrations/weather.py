"""Open-Meteo weather adapter (free, no API key).

The request URL is built from a fixed host and the site's stored coordinates only, so callers can
never steer it elsewhere (SSRF); redirects are refused. The response is untrusted input: its size
is capped and its shape validated. Tests swap in a fake ``WeatherClient``.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from app.core import clock

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class DailyWeather:
    day: date
    weather_code: int | None
    temp_max_c: float | None
    temp_min_c: float | None
    rain_mm: float | None
    rain_probability: int | None


class WeatherUnavailableError(Exception):
    """The provider could not be reached or answered with something unusable."""


class WeatherClient(Protocol):
    def daily(self, latitude: float, longitude: float, days: int) -> list[DailyWeather]: ...


class DisabledWeatherClient:
    """Used when live weather is switched off: always behaves like an outage."""

    def daily(self, latitude: float, longitude: float, days: int) -> list[DailyWeather]:
        raise WeatherUnavailableError("Live weather is turned off.")


class _Daily(BaseModel):
    time: list[date] = Field(max_length=16)
    weather_code: list[int | None]
    temperature_2m_max: list[float | None]
    temperature_2m_min: list[float | None]
    precipitation_sum: list[float | None]
    precipitation_probability_max: list[int | None]


class _Response(BaseModel):
    daily: _Daily


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could point anywhere, including internal hosts: treat it as a failure."""

    def redirect_request(self, *args: object, **kwargs: object) -> urllib.request.Request | None:
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


class OpenMeteoClient:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout = timeout_seconds

    def daily(self, latitude: float, longitude: float, days: int) -> list[DailyWeather]:
        query = urllib.parse.urlencode(
            {
                "latitude": f"{latitude:.4f}",
                "longitude": f"{longitude:.4f}",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_sum,precipitation_probability_max",
                "timezone": clock.site_zone().key,
                "forecast_days": str(days),
            }
        )
        # Fixed https host (no file: or custom schemes); only the encoded query varies.
        request = urllib.request.Request(  # noqa: S310
            f"{OPEN_METEO_URL}?{query}", headers={"User-Agent": "SiteSense"}
        )
        try:
            with NO_REDIRECT_OPENER.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WeatherUnavailableError(str(exc)) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise WeatherUnavailableError("Weather response too large.")
        try:
            parsed = _Response.model_validate(json.loads(raw))
        except (ValueError, ValidationError) as exc:
            raise WeatherUnavailableError("Unexpected weather response.") from exc
        d = parsed.daily
        columns = (
            d.weather_code,
            d.temperature_2m_max,
            d.temperature_2m_min,
            d.precipitation_sum,
            d.precipitation_probability_max,
        )
        if any(len(column) != len(d.time) for column in columns):
            raise WeatherUnavailableError("Unexpected weather response.")
        return [
            DailyWeather(
                day=d.time[i],
                weather_code=d.weather_code[i],
                temp_max_c=d.temperature_2m_max[i],
                temp_min_c=d.temperature_2m_min[i],
                rain_mm=d.precipitation_sum[i],
                rain_probability=d.precipitation_probability_max[i],
            )
            for i in range(len(d.time))
        ]
