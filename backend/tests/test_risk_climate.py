"""Risk model 1.2 (issue #27): the rain climate behind ``wet_days_ahead``."""

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.ai.risk import climate
from app.ai.risk import features as feature_builder
from app.models import Site
from tests.materials_fixtures import Boq

# January 10%, February 20%, ... so each month's share is easy to read back.
TOWN = climate.Town("test", 0.0, 0.0, tuple(round(0.1 * (m + 1), 1) for m in range(12)))


def test_wet_days_ahead_counts_working_days_to_the_planned_end() -> None:
    # Sun 11 Oct to Sat 31 Oct: 18 working days in October at 1.0 each.
    assert climate.wet_days_ahead(TOWN, date(2026, 10, 11), date(2026, 10, 31)) == pytest.approx(
        18 * 1.0 + 6 * 1.1  # at least 28 days: Mon 2 to Sat 7 November too
    )
    # A long programme: tomorrow to the planned end, Sundays excluded.
    assert climate.wet_days_ahead(TOWN, date(2026, 10, 31), date(2026, 11, 30)) == pytest.approx(25 * 1.1)


def test_past_the_planned_end_the_next_four_weeks_still_count() -> None:
    # Planned end long gone: Mon 2 Feb to Sat 28 Feb, 24 working days.
    assert climate.wet_days_ahead(TOWN, date(2026, 2, 1), date(2025, 6, 30)) == pytest.approx(24 * 0.2)


@pytest.mark.parametrize(
    ("latitude", "longitude", "town"),
    [
        (6.8836, 79.8650, "colombo"),  # Havelock Town
        (7.2735, 80.6127, "kandy"),  # Peradeniya
        (6.0329, 80.2168, "galle"),
        (9.6600, 80.0200, "jaffna"),
        (7.9500, 81.5500, "batticaloa"),  # nearer Batticaloa than any wet-zone town
    ],
)
def test_a_site_uses_its_nearest_town(latitude: float, longitude: float, town: str) -> None:
    found = climate.nearest(latitude, longitude)

    assert found.town.name == town
    assert found.distance_km < 50


def test_the_shipped_climate_has_both_monsoons() -> None:
    towns = {t.name: t for t in climate.towns()}

    assert len(towns) == 7
    # Colombo's wettest months are in the south-west monsoon and the inter-monsoon (May, Oct, Nov);
    # Batticaloa's are in the north-east monsoon (Oct to Dec) and it is dry in June and July.
    assert towns["colombo"].heavy_day_share[4] > 0.3 > towns["colombo"].heavy_day_share[1]
    assert towns["batticaloa"].heavy_day_share[10] > 0.3 > 0.05 > towns["batticaloa"].heavy_day_share[5]


def test_the_feature_uses_the_sites_climate(db: Session, boq: Boq, mat_site: Site) -> None:
    on = date(2026, 7, 6)
    mat_site.latitude, mat_site.longitude = 6.8836, 79.8650
    db.commit()

    built = feature_builder.build(db, boq.project, on)

    colombo = climate.nearest(6.8836, 79.8650).town
    expected = climate.wet_days_ahead(colombo, on, boq.project.planned_end)
    assert built.values["wet_days_ahead"] == pytest.approx(expected, abs=1e-4)
    assert expected > 100  # eighteen months of Colombo's weather still ahead
    assert not any("coordinates" in n for n in built.notes)


def test_a_site_without_coordinates_uses_the_national_average(db: Session, boq: Boq) -> None:
    on = date(2026, 7, 6)

    built = feature_builder.build(db, boq.project, on)

    expected = climate.wet_days_ahead(climate.national_average(), on, boq.project.planned_end)
    assert built.values["wet_days_ahead"] == pytest.approx(expected, abs=1e-4)
    assert any("no coordinates" in n for n in built.notes)


def town_file(latitude: float = 7, shares: object = None) -> str:
    shares = [0.1] * 12 if shares is None else shares
    town = {"latitude": latitude, "longitude": 80, "heavy_day_share_by_month": shares}
    return json.dumps({"towns": {"x": town}})


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({"towns": {}}),
        town_file(shares=[0.1] * 11),
        town_file(shares=[1.5] * 12),
        town_file(shares=["0.1"] * 12),
        town_file(latitude=99),
    ],
)
def test_a_bad_climate_file_is_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "climate.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(climate.ClimateError):
        climate.towns(path)


def test_a_missing_climate_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(climate.ClimateError):
        climate.towns(tmp_path / "nothing.json")
