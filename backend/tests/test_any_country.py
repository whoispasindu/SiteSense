"""Any country: the company's time zone, currency and holidays are settings, and the risk model copes.

- Time zone, country, currency and number format come from SITESENSE_* settings (Sri Lanka's by default).
- The risk model reads the contract value in LKR millions: other currencies are converted with
  SITESENSE_RISK_LKR_PER_UNIT, which is required unless the currency is LKR.
- Rain ahead: Sri Lankan sites use the nearest of the seven towns; sites elsewhere their own history
  (fetched once from the Open-Meteo archive); until then, the towns' average with a note.
- Public holidays can be imported by country and year.
"""

import io
import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.risk import climate, scoring
from app.ai.risk import features as feature_builder
from app.core import clock, company
from app.core.permissions import Role
from app.core.scheduler import refresh_rain_climates
from app.integrations import weather as provider
from app.integrations.climate import OpenMeteoArchiveClient
from app.integrations.weather import WeatherUnavailableError
from app.models import AuditLog, Holiday, Site, User
from tests.conftest import bearer, login, make_settings
from tests.materials_fixtures import Boq

LONDON = (51.5072, -0.1276)
HAVELOCK = (6.8836, 79.8650)


@pytest.fixture
def company_settings() -> Iterator[Callable[..., company.Company]]:
    """Configure the process-wide company settings for one test, then put Sri Lanka's back."""

    def configure(**overrides: object) -> company.Company:
        return company.configure(make_settings(**overrides))

    yield configure
    company.configure(make_settings())


# --- Settings ---------------------------------------------------------------------------------


def test_the_defaults_are_sri_lankas() -> None:
    settings = make_settings()
    assert (settings.time_zone, settings.country, settings.currency) == ("Asia/Colombo", "LK", "LKR")
    assert settings.lkr_per_unit == 1


def test_another_currency_needs_the_risk_models_rate() -> None:
    with pytest.raises(ValidationError, match="SITESENSE_RISK_LKR_PER_UNIT"):
        make_settings(currency="GBP")
    assert make_settings(currency="GBP", risk_lkr_per_unit="395.5").lkr_per_unit == Decimal("395.5")


@pytest.mark.parametrize(
    "overrides",
    [
        {"risk_lkr_per_unit": "2"},  # LKR is LKR
        {"time_zone": "Mars/Olympus_Mons"},
        {"currency": "pounds", "risk_lkr_per_unit": "1"},
        {"country": "GBR"},
        {"number_locale": "en_GB"},
        {"currency": "GBP", "risk_lkr_per_unit": "0"},
    ],
)
def test_bad_company_settings_are_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_today_on_site_follows_the_company_time_zone(
    company_settings: Callable[..., company.Company], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 23:30 UTC on 14 November: already the 15th in Colombo and Auckland, still the 14th in Chicago.
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2026, 11, 14, 23, 30, tzinfo=UTC))
    assert clock.site_today() == date(2026, 11, 15)
    company_settings(time_zone="America/Chicago")
    assert clock.site_today() == date(2026, 11, 14)
    assert str(clock.site_zone()) == "America/Chicago"


def test_amounts_in_messages_use_the_companys_currency(
    company_settings: Callable[..., company.Company],
) -> None:
    assert company.money(Decimal("1250000.5")) == "LKR 1,250,000.50"
    company_settings(currency="JPY", risk_lkr_per_unit="2.05")
    assert company.money(Decimal("1250000")) == "JPY 1,250,000"
    company_settings(currency="GBP", risk_lkr_per_unit="395")
    assert company.money(Decimal("99.5")) == "GBP 99.50"


def test_me_tells_the_web_app_the_companys_locale(api: TestClient, make_user: Callable[..., User]) -> None:
    user = make_user(Role.SITE_ENGINEER)
    body = api.get("/api/v1/me", headers=bearer(login(api, user.email))).json()
    assert body["company"] == {
        "time_zone": "Asia/Colombo",
        "country": "LK",
        "currency": "LKR",
        "currency_decimals": 2,
        "number_locale": "en-LK",
    }


# --- Risk model: the contract value ------------------------------------------------------------


def test_the_contract_value_reaches_the_model_in_lkr(
    company_settings: Callable[..., company.Company],
) -> None:
    assert feature_builder.contract_value_m(Decimal("685000000")) == pytest.approx(685)
    company_settings(currency="GBP", risk_lkr_per_unit="400")
    # GBP 1.7 M is LKR 680 M to the model, and people still read pounds.
    assert feature_builder.contract_value_m(Decimal("1700000")) == pytest.approx(680)
    assert scoring.describe("contract_value_m", {"contract_value_m": 680.0}) == "GBP 1.7 M"


def test_a_foreign_project_scores_like_the_same_project_in_rupees(
    db: Session, boq: Boq, company_settings: Callable[..., company.Company]
) -> None:
    on = date(2026, 7, 6)
    in_rupees = feature_builder.build(db, boq.project, on).values
    company_settings(currency="GBP", risk_lkr_per_unit="400")
    boq.project.contract_value = boq.project.contract_value / 400
    db.commit()

    in_pounds = feature_builder.build(db, boq.project, on).values

    assert in_pounds["contract_value_m"] == pytest.approx(in_rupees["contract_value_m"], rel=1e-6)


# --- Risk model: the rain climate --------------------------------------------------------------

# Twelve monthly shares, easy to recognise.
OWN = [0.05, 0.04, 0.06, 0.05, 0.05, 0.06, 0.04, 0.05, 0.07, 0.09, 0.1, 0.08]


def test_a_sri_lankan_site_keeps_its_nearest_town() -> None:
    choice = climate.for_site(*HAVELOCK, OWN)
    assert choice.town.name == "colombo"
    assert choice.note is None
    assert not climate.needs_own(*HAVELOCK)


def test_a_site_elsewhere_uses_its_own_climate() -> None:
    assert climate.needs_own(*LONDON)
    choice = climate.for_site(*LONDON, OWN)
    assert choice.town.heavy_day_share == tuple(OWN)
    assert choice.note is None


def test_until_its_history_is_fetched_a_site_elsewhere_uses_the_average_and_says_so() -> None:
    choice = climate.for_site(*LONDON, None)
    assert choice.town == climate.national_average()
    assert choice.note is not None
    assert "not been fetched yet" in choice.note


def test_india_just_across_the_strait_is_not_sri_lanka() -> None:
    assert climate.needs_own(9.2876, 79.3129)  # Rameswaram
    assert not climate.needs_own(9.6615, 80.0255)  # Jaffna


def test_heavy_day_shares_match_the_training_sums() -> None:
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(366)]
    # Every January day heavy, every tenth day of the rest heavy, a missing value counts as dry.
    rain: list[float | None] = [
        25.0 if d.month == 1 else (10.0 if i % 10 == 0 else 2.0) for i, d in enumerate(days)
    ]
    rain[40] = None
    shares = climate.heavy_day_shares(days, rain)
    assert shares[0] == 1.0
    feb = [r for d, r in zip(days, rain, strict=True) if d.month == 2]
    assert shares[1] == round(sum(1 for r in feb if r is not None and r >= 10) / len(feb), 4)


def test_a_history_missing_a_month_is_refused() -> None:
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(31)]
    with pytest.raises(climate.ClimateError):
        climate.heavy_day_shares(days, [1.0] * 31)


def test_the_feature_uses_a_foreign_sites_own_climate(db: Session, boq: Boq, mat_site: Site) -> None:
    on = date(2026, 7, 6)
    mat_site.latitude, mat_site.longitude = LONDON
    db.commit()
    pending = feature_builder.build(db, boq.project, on)
    assert any("not been fetched yet" in n for n in pending.notes)

    mat_site.rain_climate = OWN
    db.commit()
    built = feature_builder.build(db, boq.project, on)

    expected = climate.wet_days_ahead(climate.own(OWN), on, boq.project.planned_end)
    assert built.values["wet_days_ahead"] == pytest.approx(expected, abs=1e-4)
    assert built.values["wet_days_ahead"] < pending.values["wet_days_ahead"]  # London is drier
    assert not any("fetched" in n for n in built.notes)


class FakeArchive:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[float, float]] = []
        self.fail = fail

    def daily_rain(self, latitude: float, longitude: float) -> tuple[list[date], list[float | None]]:
        self.calls.append((latitude, longitude))
        if self.fail:
            raise WeatherUnavailableError("archive down")
        days = [date(2024, 1, 1) + timedelta(days=i) for i in range(366)]
        return days, [12.0 if d.month == 11 else 0.0 for d in days]


def _located_site(db: Session, code: str, at: tuple[float, float]) -> Site:
    site = Site(code=code, name=code, location=code, latitude=at[0], longitude=at[1])
    db.add(site)
    db.commit()
    return site


def test_the_weather_refresh_fetches_climates_only_where_needed(db: Session) -> None:
    london_id = _located_site(db, "LON-1", LONDON).id
    havelock_id = _located_site(db, "COL-9", HAVELOCK).id
    archive = FakeArchive()

    fetched = refresh_rain_climates(lambda: db, archive)  # the job closes the session it is given

    assert fetched == 1
    assert archive.calls == [LONDON]
    london, havelock = db.get_one(Site, london_id), db.get_one(Site, havelock_id)
    assert london.rain_climate is not None
    assert london.rain_climate[10] == 1.0
    assert london.rain_climate_at is not None
    assert havelock.rain_climate is None
    # Fetched once: the next morning there is nothing to do.
    assert refresh_rain_climates(lambda: db, archive) == 0


def test_a_failed_fetch_is_retried_next_time(db: Session) -> None:
    london_id = _located_site(db, "LON-2", LONDON).id
    assert refresh_rain_climates(lambda: db, FakeArchive(fail=True)) == 0
    assert db.get_one(Site, london_id).rain_climate is None


def test_moving_a_site_clears_its_climate(
    api: TestClient, db: Session, make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN)
    london = _located_site(db, "LON-3", LONDON)
    london.rain_climate = OWN
    db.commit()
    headers = bearer(login(api, admin.email))

    renamed = api.patch(f"/api/v1/admin/sites/{london.id}", json={"name": "London Bridge"}, headers=headers)
    assert renamed.status_code == 200, renamed.text
    db.refresh(london)
    assert london.rain_climate == OWN

    moved = api.patch(
        f"/api/v1/admin/sites/{london.id}", json={"latitude": 53.4808, "longitude": -2.2426}, headers=headers
    )
    assert moved.status_code == 200, moved.text
    db.refresh(london)
    assert london.rain_climate is None
    assert london.rain_climate_at is None


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_the_archive_request_and_its_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    payload = {"daily": {"time": ["2012-01-01", "2012-01-02"], "precipitation_sum": [3.2, None]}}

    def fake_open(request: Any, timeout: float) -> _FakeResponse:
        seen["url"], seen["timeout"] = request.full_url, timeout
        return _FakeResponse(json.dumps(payload).encode())

    monkeypatch.setattr(provider.NO_REDIRECT_OPENER, "open", fake_open)
    days, rain = OpenMeteoArchiveClient(timeout_seconds=30).daily_rain(51.50721234, -0.1276)

    assert seen["url"].startswith(
        "https://archive-api.open-meteo.com/v1/archive?latitude=51.5072&longitude=-0.1276"
    )
    assert "start_date=2012-01-01" in seen["url"]
    assert "end_date=2025-12-31" in seen["url"]
    assert seen["timeout"] == 30
    assert days == [date(2012, 1, 1), date(2012, 1, 2)]
    assert rain == [3.2, None]

    payload["daily"]["precipitation_sum"] = [1.0]  # columns of different lengths
    with pytest.raises(WeatherUnavailableError):
        OpenMeteoArchiveClient(timeout_seconds=30).daily_rain(*LONDON)


# --- Holidays ----------------------------------------------------------------------------------

IMPORT = "/api/v1/admin/holidays/import"


@pytest.fixture
def admin_headers(api: TestClient, make_user: Callable[..., User]) -> dict[str, str]:
    return bearer(login(api, make_user(Role.ADMIN).email))


def test_sri_lankas_public_holidays_import_with_poya_days(
    api: TestClient, db: Session, admin_headers: dict[str, str]
) -> None:
    db.execute(delete(Holiday))  # the 2026 seed (migration 0011): start from an empty calendar
    db.add(Holiday(holiday_date=date(2026, 1, 3), name="Our own name", created_at=clock.utcnow()))
    db.commit()

    body = api.post(IMPORT, json={"country": "LK", "year": 2026}, headers=admin_headers).json()

    names = {h["holiday_date"]: h["name"] for h in body["added"]}
    assert names["2026-06-29"] == "Poson Full Moon Poya Day"
    assert names["2026-02-04"] == "Independence Day"
    assert "2026-01-03" not in names  # already entered: left as it was
    assert body["already_entered"] == 1
    stored = db.scalars(select(Holiday).where(Holiday.holiday_date == date(2026, 1, 3))).one()
    assert stored.name == "Our own name"
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "holidays.imported")).one()
    assert entry.details == {"country": "LK", "year": 2026, "added": len(body["added"])}

    again = api.post(IMPORT, json={"country": "LK", "year": 2026}, headers=admin_headers).json()
    assert again["added"] == []
    assert "already entered" in again["message"]


def test_another_countrys_holidays_import(api: TestClient, admin_headers: dict[str, str]) -> None:
    body = api.post(IMPORT, json={"country": "GB", "year": 2027}, headers=admin_headers).json()
    names = {h["holiday_date"]: h["name"] for h in body["added"]}
    assert names["2027-12-25"] == "Christmas Day"


def test_a_year_not_published_yet_says_so(api: TestClient, admin_headers: dict[str, str]) -> None:
    body = api.post(IMPORT, json={"country": "LK", "year": 2031}, headers=admin_headers).json()
    assert body["added"] == []
    assert "No public holidays are published" in body["message"]


def test_an_unknown_country_is_refused(api: TestClient, admin_headers: dict[str, str]) -> None:
    response = api.post(IMPORT, json={"country": "ZZ", "year": 2027}, headers=admin_headers)
    assert response.status_code == 422
    assert "no public holiday list for ZZ" in response.json()["error"]["message"]


def test_the_import_offers_the_companys_country_first(api: TestClient, admin_headers: dict[str, str]) -> None:
    body = api.get("/api/v1/admin/holidays/countries", headers=admin_headers).json()
    assert body["default"] == "LK"
    assert {"LK", "GB", "AE", "IN", "AU"} <= set(body["countries"])
