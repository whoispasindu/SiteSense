"""Shared fixtures for the Phase 4 tests: a running project, people on its site, fake weather."""

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.core import clock
from app.core.permissions import Role
from app.integrations.weather import DailyWeather, WeatherUnavailableError
from app.models import Project, Site, Task, User
from tests.conftest import bearer, login

# The real site date: report timestamps come from the real clock (tokens need it), and the
# "same day" editing rule compares the two.
TODAY = clock.site_today()


@dataclass
class FakeWeather:
    """Stands in for Open-Meteo. Set ``fail`` to simulate an outage (TC-08)."""

    fail: bool = False
    calls: int = 0
    days: list[DailyWeather] = field(default_factory=list)

    def daily(self, latitude: float, longitude: float, days: int) -> list[DailyWeather]:
        self.calls += 1
        if self.fail:
            raise WeatherUnavailableError("connection refused")
        return self.days[:days]


def sample_days(start: date = TODAY, count: int = 5) -> list[DailyWeather]:
    from datetime import timedelta

    return [
        DailyWeather(
            day=start + timedelta(days=i),
            weather_code=61 if i % 2 else 2,
            temp_max_c=31.0 + i / 10,
            temp_min_c=24.5,
            rain_mm=12.4 if i % 2 else 0.0,
            rain_probability=80 if i % 2 else 10,
        )
        for i in range(count)
    ]


@pytest.fixture
def site_today(monkeypatch: pytest.MonkeyPatch) -> Callable[[date], None]:
    """Pin the site's calendar date (token clocks keep real time)."""

    def set_today(day: date) -> None:
        monkeypatch.setattr(clock, "site_today", lambda: day)

    set_today(TODAY)
    return set_today


@pytest.fixture
def fake_weather(app: FastAPI) -> FakeWeather:
    fake = FakeWeather(days=sample_days())
    app.state.weather_client = fake
    return fake


@pytest.fixture
def report_site(make_site: Callable[..., Site], db: Session) -> Site:
    site = make_site("COL-07")
    site.latitude, site.longitude = 6.8836, 79.8650
    db.commit()
    return site


@pytest.fixture
def report_project(db: Session, report_site: Site) -> Project:
    project = Project(
        code="HR-1",
        name="Havelock",
        site_id=report_site.id,
        client_name="Client",
        project_type="residential",
        status="active",
        contract_value=Decimal("1000000.00"),
        start_date=date(2026, 3, 1),
        planned_end=date(2027, 3, 31),
    )
    db.add(project)
    db.commit()
    return project


@pytest.fixture
def report_task(db: Session, report_project: Project) -> Task:
    task = Task(
        project_id=report_project.id,
        code="T-010",
        name="Frame level 4",
        planned_start=date(2026, 9, 1),
        planned_end=date(2026, 11, 30),
        weight=Decimal("40.00"),
        percent_complete=Decimal("20.00"),
        position=1,
    )
    db.add(task)
    db.commit()
    return task


@dataclass(frozen=True)
class Person:
    user: User
    headers: dict[str, str]


@pytest.fixture
def person(api: TestClient, make_user: Callable[..., User], report_site: Site) -> Callable[..., Person]:
    """A signed-in user with the given role, assigned to the report site unless told otherwise."""

    def factory(role: Role, *, sites: list[Site] | None = None) -> Person:
        user = make_user(role, sites=[report_site] if sites is None else sites)
        return Person(user, bearer(login(api, user.email)))

    return factory


@pytest.fixture
def engineer(person: Callable[..., Person]) -> Person:
    return person(Role.SITE_ENGINEER)


@pytest.fixture
def manager(person: Callable[..., Person]) -> Person:
    return person(Role.PROJECT_MANAGER)


def report_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "report_date": TODAY.isoformat(),
        "crew_count": 42,
        "work_done": "Fixed reinforcement for the level 4 slab on grids A to D.",
        "problems": "Cement delivery late again.",
        "weather_summary": "Light rain",
        "temp_max_c": "30.5",
        "temp_min_c": "24.0",
        "rain_mm": "6.2",
        "weather_source": "manual",
    }
    body.update(overrides)
    return body


def image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (64, 48), **save: object) -> bytes:
    out = io.BytesIO()
    mode = "RGBA" if fmt == "PNG" else "RGB"
    Image.new(mode, size, (200, 120, 40)).save(out, format=fmt, **save)
    return out.getvalue()
