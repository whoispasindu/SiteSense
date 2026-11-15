import io
import json
import urllib.error
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.integrations import weather as provider
from app.integrations.weather import DailyWeather, OpenMeteoClient, WeatherUnavailableError
from app.models import Project, Site, WeatherForecast
from app.services import weather
from tests.report_fixtures import TODAY, FakeWeather, Person

pytestmark = pytest.mark.usefixtures("site_today")


def weather_url(project: Project) -> str:
    return f"/api/v1/projects/{project.id}/weather"


def age_cache(db: Session, hours: int) -> None:
    """Make the cached forecast older (moving the clock would also expire the login)."""
    db.execute(update(WeatherForecast).values(fetched_at=clock.utcnow() - timedelta(hours=hours)))
    db.commit()


def test_forecast_is_fetched_cached_and_shown(
    api: TestClient, report_project: Project, engineer: Person, fake_weather: FakeWeather, db: Session
) -> None:
    body = api.get(weather_url(report_project), headers=engineer.headers).json()

    assert body["available"] is True
    assert body["stale"] is False
    assert body["message"] is None
    assert body["site_code"] == "COL-07"
    assert body["heavy_rain_threshold_mm"] == "10.0"
    assert [d["date"] for d in body["days"]] == [(TODAY + timedelta(days=i)).isoformat() for i in range(5)]
    assert body["days"][1] == {
        "date": (TODAY + timedelta(days=1)).isoformat(), "summary": "Light rain", "weather_code": 61,
        "temp_max_c": "31.1", "temp_min_c": "24.5", "rain_mm": "12.4", "rain_probability": 80,
    }  # fmt: skip
    assert db.scalar(select(func.count(WeatherForecast.id))) == 5

    api.get(weather_url(report_project), headers=engineer.headers)
    assert fake_weather.calls == 1  # the second request is served from the cache


def test_stale_cache_is_refreshed(
    api: TestClient,
    report_project: Project,
    engineer: Person,
    fake_weather: FakeWeather,
    db: Session,
) -> None:
    api.get(weather_url(report_project), headers=engineer.headers)
    age_cache(db, 4)

    api.get(weather_url(report_project), headers=engineer.headers)

    assert fake_weather.calls == 2


def test_api_down_serves_the_last_cached_forecast(
    api: TestClient,
    report_project: Project,
    engineer: Person,
    fake_weather: FakeWeather,
    db: Session,
) -> None:
    """TC-08: last cached forecast used, warning shown, no crash."""
    api.get(weather_url(report_project), headers=engineer.headers)
    age_cache(db, 6)
    fake_weather.fail = True

    response = api.get(weather_url(report_project), headers=engineer.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["stale"] is True
    assert "unavailable" in body["message"]
    assert len(body["days"]) == 5


def test_api_down_with_nothing_cached_still_answers(
    api: TestClient, report_project: Project, engineer: Person, fake_weather: FakeWeather
) -> None:
    fake_weather.fail = True

    response = api.get(weather_url(report_project), headers=engineer.headers)

    assert response.status_code == 200
    assert response.json() == {
        "site_code": "COL-07", "available": False, "stale": True, "fetched_at": None,
        "message": "The weather service is unavailable and nothing is cached yet.", "days": [],
        "heavy_rain_threshold_mm": "10.0",
    }  # fmt: skip


def test_site_without_coordinates_explains_what_to_do(
    api: TestClient,
    report_project: Project,
    report_site: Site,
    engineer: Person,
    fake_weather: FakeWeather,
    db: Session,
) -> None:
    report_site.latitude = None
    report_site.longitude = None
    db.commit()

    body = api.get(weather_url(report_project), headers=engineer.headers).json()

    assert body["available"] is False
    assert "coordinates" in body["message"]
    assert fake_weather.calls == 0


def test_weather_is_scoped_to_the_users_sites(
    api: TestClient, report_project: Project, person: Callable[..., Person], make_site: Callable[..., Site]
) -> None:
    from app.core.permissions import Role

    outsider = person(Role.SITE_ENGINEER, sites=[make_site("KDY-02")])

    assert api.get(weather_url(report_project), headers=outsider.headers).status_code == 404


def test_out_of_range_values_are_not_stored(db: Session, report_site: Site) -> None:
    client = FakeWeather(days=[DailyWeather(TODAY, 999, 150.0, -100.0, -5.0, 250)])

    weather.refresh(db, report_site, client)

    row = db.scalar(select(WeatherForecast))
    assert row is not None
    assert row.summary == "Unknown"
    assert (row.temp_max_c, row.temp_min_c, row.rain_mm, row.rain_probability) == (None, None, None, None)


def test_disabled_client_behaves_like_an_outage() -> None:
    with pytest.raises(WeatherUnavailableError):
        provider.DisabledWeatherClient().daily(6.9, 79.8, 5)


# --- Open-Meteo adapter: the response is untrusted input ------------------------------------------


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _payload(**overrides: Any) -> dict[str, Any]:
    daily: dict[str, Any] = {
        "time": ["2026-10-09", "2026-10-10"],
        "weather_code": [3, 95],
        "temperature_2m_max": [31.2, 29.0],
        "temperature_2m_min": [24.1, 23.8],
        "precipitation_sum": [0.0, 18.3],
        "precipitation_probability_max": [10, 90],
    }
    daily.update(overrides)
    return {"daily": daily}


@pytest.fixture
def opener(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"body": json.dumps(_payload()).encode(), "error": None, "url": None}

    def fake_open(request: Any, timeout: float) -> _FakeResponse:
        state["url"] = request.full_url
        state["timeout"] = timeout
        if state["error"] is not None:
            raise state["error"]
        return _FakeResponse(state["body"])

    monkeypatch.setattr(provider.NO_REDIRECT_OPENER, "open", fake_open)
    return state


def test_open_meteo_request_and_parsing(opener: dict[str, Any]) -> None:
    days = OpenMeteoClient(timeout_seconds=4).daily(6.88361234, 79.865, 5)

    assert opener["url"].startswith(
        "https://api.open-meteo.com/v1/forecast?latitude=6.8836&longitude=79.8650"
    )
    assert "forecast_days=5" in opener["url"]
    assert opener["timeout"] == 4
    assert [(d.day.isoformat(), d.weather_code, d.rain_mm) for d in days] == [
        ("2026-10-09", 3, 0.0),
        ("2026-10-10", 95, 18.3),
    ]
    assert weather.describe(95) == "Thunderstorm"


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"{}",
        json.dumps(_payload(weather_code=[1])).encode(),  # columns of different lengths
        json.dumps(_payload(time=["yesterday", "today"])).encode(),
        json.dumps(_payload(time=[f"2026-10-{d:02d}" for d in range(1, 20)])).encode(),  # too many days
        b"{" + b" " * (64 * 1024) + b"}",  # oversized
    ],
    ids=["not-json", "no-daily", "ragged", "bad-dates", "too-many-days", "oversized"],
)
def test_unusable_responses_are_rejected(opener: dict[str, Any], body: bytes) -> None:
    opener["body"] = body

    with pytest.raises(WeatherUnavailableError):
        OpenMeteoClient(timeout_seconds=1).daily(6.9, 79.8, 5)


@pytest.mark.parametrize(
    "error",
    [urllib.error.URLError("no route"), TimeoutError(), ConnectionResetError()],
    ids=["url-error", "timeout", "reset"],
)
def test_network_failures_become_weather_unavailable(opener: dict[str, Any], error: Exception) -> None:
    opener["error"] = error

    with pytest.raises(WeatherUnavailableError):
        OpenMeteoClient(timeout_seconds=1).daily(6.9, 79.8, 5)


def test_redirects_are_refused() -> None:
    handler = provider._NoRedirect()

    assert handler.redirect_request() is None


def test_cached_forecast_for_a_day(db: Session, report_site: Site) -> None:
    weather.refresh(db, report_site, FakeWeather(days=[DailyWeather(TODAY, 2, 30.0, 24.0, 0.0, 5)]))

    assert weather.for_day(db, report_site.id, TODAY) is not None
    assert weather.for_day(db, report_site.id, TODAY + timedelta(days=9)) is None
    assert clock.site_today() == TODAY
