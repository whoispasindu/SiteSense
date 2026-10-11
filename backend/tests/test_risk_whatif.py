"""Phase 10: the what-if planner. Recovery actions, their effects as ranges, costs, and advice."""

import itertools
import random
import uuid
from collections.abc import Callable
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.ai.risk import model as risk_model
from app.ai.risk import whatif
from app.core.permissions import Role
from app.models import Site
from tests.materials_fixtures import Boq, Who

ON = date(2026, 7, 6)
FEATURES = risk_model.current().features


def values(**overrides: float) -> dict[str, float]:
    return dict.fromkeys(FEATURES, 0.0) | overrides


# --- The catalogue (no database) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "points", "strength", "after"),
    [
        (-30.0, 20, 1.0, -10.0),
        (-30.0, 20, 0.5, -20.0),  # half its planned change
        (0.0, 20, 1.0, 10.0),  # never past 10% over plan
        (15.0, 20, 1.0, 15.0),  # already over the cap: unchanged, never lowered
    ],
)
def test_more_crew_up_to_ten_percent_over_plan(
    before: float, points: float, strength: float, after: float
) -> None:
    action = "add_crew" if points == 20 else "work_sundays"

    assert whatif.applied(values(crew_vs_plan_pct=before), [action], strength)["crew_vs_plan_pct"] == after


def test_crew_actions_together_still_stop_at_the_cap() -> None:
    out = whatif.applied(values(crew_vs_plan_pct=-30), ["add_crew", "work_sundays"], 1.0)

    assert out["crew_vs_plan_pct"] == 5.0  # -30 + 20 + 15
    assert (
        whatif.applied(values(crew_vs_plan_pct=-10), ["add_crew", "work_sundays"], 1.0)["crew_vs_plan_pct"]
        == 10.0
    )


def test_expediting_and_weather_protection() -> None:
    before = values(late_deliveries_count=4, avg_lateness_days=8, wet_days_ahead=50, rain_days_next_14=6)

    full = whatif.applied(before, ["expedite_materials", "weather_protection"], 1.0)
    half = whatif.applied(before, ["expedite_materials", "weather_protection"], 0.5)

    assert (full["late_deliveries_count"], full["avg_lateness_days"]) == (2.0, 4.0)
    assert (full["wet_days_ahead"], full["rain_days_next_14"]) == pytest.approx((35.0, 3.0))
    assert (half["late_deliveries_count"], half["wet_days_ahead"]) == pytest.approx((3.0, 42.5))
    assert before["late_deliveries_count"] == 4  # the input is never changed in place


def test_an_action_says_what_it_changes() -> None:
    before = values(crew_vs_plan_pct=-12)
    action = whatif.BY_ID["add_crew"]

    assert whatif.describe_change(action, before, whatif.applied(before, ["add_crew"], 1.0)) == (
        "crew -12% to +8% against plan"
    )
    on_plan = values(crew_vs_plan_pct=12)
    assert whatif.describe_change(action, on_plan, on_plan).startswith("nothing to change: ")


def test_management_actions_are_advice_only() -> None:
    assert whatif.advice(values()) == []
    advice = whatif.advice(values(missing_reports_14=4, issues_safety_14=1, issues_material_14=2))

    assert [a.id for a in advice] == ["file_reports", "follow_up_issues"]
    assert "4 working days" in advice[0].text
    assert "changes no forecast" in advice[0].text
    assert "3 issues" in advice[1].text


# --- TC: no recovery action ever makes the forecast worse ---------------------------------------------


def test_no_action_or_combination_ever_makes_a_forecast_worse() -> None:
    """The guide's sanity check, on the shipped model: every action, alone and together, at half and full
    strength, on the golden rows and on varied projects. Neither forecast nor either end of its range
    may rise."""
    model = risk_model.current()
    rng = random.Random(27)  # noqa: S311 - a repeatable test sample, not a secret
    rows = [dict(zip(FEATURES, row["x"], strict=True)) for row in model.golden]
    for row in list(rows):
        varied = dict(row)
        varied |= {
            "crew_vs_plan_pct": rng.uniform(-40, 15),
            "late_deliveries_count": rng.uniform(0, 12),
            "avg_lateness_days": rng.uniform(0, 20),
            "wet_days_ahead": rng.uniform(0, 150),
            "rain_days_next_14": rng.uniform(0, 10),
        }
        rows.append(varied)
    ids = [a.id for a in whatif.CATALOGUE]
    combos = [list(c) for n in range(1, len(ids) + 1) for c in itertools.combinations(ids, n)]
    for row in rows:
        before = model.predict(tuple(row[f] for f in FEATURES))
        for combo in combos:
            for strength in (whatif.HALF, whatif.FULL):
                after = model.predict(tuple(whatif.applied(row, combo, strength)[f] for f in FEATURES))
                for b, a in zip(before, after, strict=True):
                    assert a.value <= b.value + 1e-9, (combo, strength)
                    assert a.low <= b.low + 1e-9, (combo, strength)
                    assert a.high <= b.high + 1e-9, (combo, strength)


# --- The endpoint ---------------------------------------------------------------------------------------


@pytest.fixture
def behind(boq: Boq) -> Boq:
    """Havelock, half a year in, with a short crew planned (so crew actions have something to do)."""
    boq.project.planned_crew = 50
    return boq


def plan(api: TestClient, boq: Boq, who: Who, actions: list[dict[str, object]]):  # type: ignore[no-untyped-def]
    return api.post(
        f"/api/v1/projects/{boq.project.id}/risk/what-if", json={"actions": actions}, headers=who.headers
    )


def test_the_planner_shows_each_action_as_a_range_and_the_plan_with_its_costs(
    api: TestClient, behind: Boq, pm: Who, site_today: Callable[[date], None]
) -> None:
    site_today(ON)

    response = plan(
        api,
        behind,
        pm,
        [{"id": "add_crew", "cost": "440000.00"}, {"id": "weather_protection"}],  # the budget is LKR 4.4 M
    )

    assert response.status_code == 200, response.text
    body = response.json()
    base = body["baseline"]
    assert base["delay_range"]["low"] <= base["delay_days"] <= base["delay_range"]["high"]
    assert [a["id"] for a in body["actions"]] == [a.id for a in whatif.CATALOGUE]  # every action, each alone
    crew = next(a for a in body["actions"] if a["id"] == "add_crew")
    assert crew["selected"] is True
    assert 0 <= crew["delay_saved_days"]["low"] <= crew["delay_saved_days"]["high"]
    assert crew["cost"] == "440000.00"
    assert crew["cost_pct"] == pytest.approx(10.0)
    assert "crew" in crew["change"]
    assert body["costs_not_entered"] == ["Weather protection"]  # blank is "cost not entered", never free
    after = body["plan"]
    assert after["delay_days"] <= base["delay_days"]
    assert after["delay_range"]["low"] <= after["delay_days"] <= after["delay_range"]["high"]
    # The entered cost (10% of the budget) is added to the cost forecast; the model's saving is less.
    model_saving = body["plan_overrun_saved_pct"]["high"] + 10.0
    assert after["overrun_pct"] == pytest.approx(base["overrun_pct"] - model_saving + 10.0, abs=0.02)
    assert body["model_version"] == risk_model.CURRENT_VERSION


def test_nothing_chosen_shows_today_and_every_action(api: TestClient, behind: Boq, pm: Who) -> None:
    body = plan(api, behind, pm, []).json()

    assert body["plan"] is None
    assert body["plan_delay_saved_days"] is None
    assert len(body["actions"]) == 4
    assert all(not a["selected"] and a["cost"] is None for a in body["actions"])


def test_without_a_budget_costs_are_kept_out_and_said(api: TestClient, behind: Boq, pm: Who, db) -> None:  # type: ignore[no-untyped-def]
    from app.models import BudgetLine

    db.query(BudgetLine).filter(BudgetLine.project_id == behind.project.id).delete()
    db.commit()

    body = plan(api, behind, pm, [{"id": "add_crew", "cost": "100000"}]).json()

    assert body["actions"][0]["cost_pct"] is None
    assert any("No cost budget yet" in n for n in body["notes"])


@pytest.mark.parametrize(
    "actions",
    [
        [{"id": "add_crew"}, {"id": "add_crew"}],
        [{"id": "pray"}],
        [{"id": "add_crew", "cost": "-1"}],
        [{"id": "add_crew", "cost": "1.234"}],
        [{"id": "add_crew", "colour": "red"}],
        [
            {"id": i}
            for i in ("add_crew", "work_sundays", "expedite_materials", "weather_protection", "add_crew")
        ],
    ],
)
def test_bad_plans_are_refused(
    api: TestClient, behind: Boq, pm: Who, actions: list[dict[str, object]]
) -> None:
    assert plan(api, behind, pm, actions).status_code == 422


@pytest.mark.parametrize("role", [Role.QUANTITY_SURVEYOR, Role.SITE_ENGINEER, Role.CLIENT, Role.ADMIN])
def test_only_project_managers_plan(
    api: TestClient, behind: Boq, team: Callable[..., Who], role: Role
) -> None:
    assert plan(api, behind, team(role), []).status_code == 403


def test_projects_on_other_sites_are_invisible(
    api: TestClient, behind: Boq, team: Callable[..., Who], make_site: Callable[..., Site]
) -> None:
    outsider = team(Role.PROJECT_MANAGER, sites=[make_site("JAF-01")])
    url = "/api/v1/projects/{}/risk/what-if"

    assert (
        api.post(url.format(behind.project.id), json={"actions": []}, headers=outsider.headers).status_code
        == 404
    )
    assert (
        api.post(url.format(uuid.uuid4()), json={"actions": []}, headers=outsider.headers).status_code == 404
    )


def test_the_planner_changes_nothing(api: TestClient, behind: Boq, pm: Who, db) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import func, select

    from app.models import AuditLog, RiskScore

    before = (db.scalar(select(func.count(RiskScore.id))), db.scalar(select(func.count(AuditLog.id))))
    plan(api, behind, pm, [{"id": "add_crew", "cost": "1000"}])

    assert (db.scalar(select(func.count(RiskScore.id))), db.scalar(select(func.count(AuditLog.id)))) == before
    assert behind.project.planned_crew == 50
