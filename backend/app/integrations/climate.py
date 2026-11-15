"""Open-Meteo archive adapter: a site's daily rainfall history, for its rain climate (free, no key).

Fetched once per site outside Sri Lanka (``services/rain_climate.py``), over the same years the
risk model's seven Sri Lankan towns come from (2012 to 2025, about 5,100 days). As with the forecast
adapter, the URL is a fixed host plus the site's stored coordinates, redirects are refused, and the
response is size-capped and validated. Tests swap in a fake ``ClimateClient``.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from app.ai.risk import climate
from app.integrations.weather import NO_REDIRECT_OPENER, WeatherUnavailableError

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MAX_RESPONSE_BYTES = 512 * 1024
MAX_DAYS = 5200  # 2012 to 2025 is 5,114 days


class ClimateClient(Protocol):
    def daily_rain(self, latitude: float, longitude: float) -> tuple[list[date], list[float | None]]: ...


class _Daily(BaseModel):
    time: list[date] = Field(max_length=MAX_DAYS)
    precipitation_sum: list[float | None] = Field(max_length=MAX_DAYS)


class _Response(BaseModel):
    daily: _Daily


class OpenMeteoArchiveClient:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout = timeout_seconds

    def daily_rain(self, latitude: float, longitude: float) -> tuple[list[date], list[float | None]]:
        query = urllib.parse.urlencode(
            {
                "latitude": f"{latitude:.4f}",
                "longitude": f"{longitude:.4f}",
                "start_date": climate.START,
                "end_date": climate.END,
                "daily": "precipitation_sum",
                # Days as the site lives them, as the towns' history is in Sri Lankan days.
                "timezone": "auto",
            }
        )
        # Fixed https host (no file: or custom schemes); only the encoded query varies.
        request = urllib.request.Request(  # noqa: S310
            f"{ARCHIVE_URL}?{query}", headers={"User-Agent": "SiteSense"}
        )
        try:
            with NO_REDIRECT_OPENER.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WeatherUnavailableError(str(exc)) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise WeatherUnavailableError("Rain history response too large.")
        try:
            parsed = _Response.model_validate(json.loads(raw))
        except (ValueError, ValidationError) as exc:
            raise WeatherUnavailableError("Unexpected rain history response.") from exc
        if len(parsed.daily.precipitation_sum) != len(parsed.daily.time):
            raise WeatherUnavailableError("Unexpected rain history response.")
        return parsed.daily.time, parsed.daily.precipitation_sum
