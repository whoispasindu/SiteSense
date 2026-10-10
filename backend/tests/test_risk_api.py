"""Phase 6: features from live data, daily scoring, the BR-10 alert, and the risk endpoints."""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.risk import features as feature_builder
from app.ai.risk import model as risk_model
from app.ai.risk.features import FEATURE_NAMES
from app.core import clock
from app.core.permissions import Role
from app.models import (
    DailyReport,
    Delivery,
    MaterialRequest,
    Notification,
    ProgressSnapshot,
    Project,
    PurchaseOrder,
    PurchaseOrderLine,
    RiskScore,
    Site,
    Supplier,
    Task,
    User,
    WeatherForecast,
)
from app.services import risk_service
from app.services.progress import TaskPlan, planned_percent
from tests.materials_fixtures import Boq, Who
from tests.report_fixtures import report_body

ON = date(2026, 7, 6)  # a Monday, half a year into the fixture project (5 Jan 2026 to 31 Dec 2027)
GAP = FEATURE_NAMES.index("progress_gap_pct")
NOW = datetime(2026, 7, 6, 4, 0, tzinfo=UTC)


# --- Builders -----------------------------------------------------------------------------------------


def add_task(db: Session, project: Project, percent: str, *, weight: str = "100") -> Task:
    task = Task(
        project_id=project.id, name="Whole job",
        planned_start=project.start_date, planned_end=project.planned_end,
        weight=Decimal(weight), percent_complete=Decimal(percent), position=1,
    )  # fmt: skip
    db.add(task)
    db.commit()
    return task


_numbers = iter(range(1, 10_000))


def add_order(
    db: Session, boq: Boq, who: User, supplier: Supplier, *,
    expected: date, deliveries: list[tuple[date, str]],
    quantity: str = "10", price: str = "2000",
) -> PurchaseOrderLine:  # fmt: skip
    n = next(_numbers)
    request = MaterialRequest(
        number=f"MR-{n:04d}", project_id=boq.project.id, boq_item_id=boq.cement.id, requested_by=who.id,
        quantity=Decimal(quantity), unit_price=Decimal(price), needed_by=expected, status="ordered",
        approval_level="qs", submitted_at=NOW,
    )  # fmt: skip
    po = PurchaseOrder(
        number=f"PO-{n:04d}", project_id=boq.project.id, supplier_id=supplier.id, issued_by=who.id,
        issued_at=NOW, expected_delivery=expected, status="issued",
    )  # fmt: skip
    db.add_all([request, po])
    db.flush()
    line = PurchaseOrderLine(
        purchase_order_id=po.id, request_id=request.id, quantity=Decimal(quantity), unit_price=Decimal(price),
        amount=Decimal(quantity) * Decimal(price), position=1,
    )  # fmt: skip
    db.add(line)
    db.flush()
    for day, qty in deliveries:
        db.add(
            Delivery(
                line_id=line.id, quantity=Decimal(qty), delivered_on=day, received_by=who.id, created_at=NOW
            )
        )
    db.commit()
    return line


def add_forecast(db: Session, site: Site, day: date, rain_mm: str) -> None:
    db.add(
        WeatherForecast(
            site_id=site.id, forecast_date=day, summary="Rain", rain_mm=Decimal(rain_mm), fetched_at=NOW
        )
    )


def add_report(db: Session, project: Project, author: User, day: date, crew: int) -> None:
    db.add(
        DailyReport(
            project_id=project.id, author_id=author.id, report_date=day, crew_count=crew,
            work_done="Blockwork.",
            submitted_at=NOW, weather_source="manual",
        )
    )  # fmt: skip


def fake_model(delay_when_behind: float = 200.0, delay_otherwise: float = 10.0) -> risk_model.RiskModel:
    """Delay depends on progress only: 10 or more points behind plan -> ``delay_when_behind`` days."""
    split = [[GAP, -10.0, 1, 2, 50.0], [-1, 0, -1, -1, delay_when_behind], [-1, 0, -1, -1, delay_otherwise]]
    return risk_model.parse(
        {
            "format": "sitesense-gbdt-v1",
            "version": "9.9.9",
            "features": list(FEATURE_NAMES),
            "targets": {"delay_days": {"trees": [split]}, "overrun_pct": {"trees": [[[-1, 0, -1, -1, 1.0]]]}},
        }
    )


# --- Feature builder --------------------------------------------------------------------------------


def test_progress_gap_and_trend(db: Session, boq: Boq) -> None:
    project = boq.project
    task = add_task(db, project, "10")
    three_weeks_ago = ON - timedelta(weeks=3)
    db.add(
        ProgressSnapshot(project_id=project.id, snapshot_date=three_weeks_ago, actual_percent=Decimal("8"))
    )
    db.add(ProgressSnapshot(project_id=project.id, snapshot_date=ON, actual_percent=Decimal("10")))  # ignored
    db.commit()
    plan = [TaskPlan(task.planned_start, task.planned_end, task.weight)]

    built = feature_builder.build(db, project, ON)

    gap_now = 10 - planned_percent(plan, ON)
    gap_then = 8 - planned_percent(plan, three_weeks_ago)
    assert built.values["progress_gap_pct"] == pytest.approx(gap_now, abs=1e-3)
    assert built.values["progress_rate_trend"] == pytest.approx((gap_now - gap_then) / 3, abs=1e-3)
    assert built.values["progress_rate_trend"] < 0  # planned work is outrunning actual work
    planned_days = (project.planned_end - project.start_date).days + 1
    assert built.values["planned_duration_days"] == planned_days
    assert built.values["elapsed_pct"] == pytest.approx(
        ((ON - project.start_date).days + 1) / planned_days * 100, abs=1e-3
    )


def test_late_and_overdue_deliveries_count_but_on_time_and_future_ones_do_not(
    db: Session, boq: Boq, buyer: Who, supplier: Supplier
) -> None:
    user = buyer.user
    add_order(
        db, boq, user, supplier, expected=ON - timedelta(days=10), deliveries=[(ON - timedelta(days=6), "10")]
    )  # 4 late
    add_order(db, boq, user, supplier, expected=ON - timedelta(days=5), deliveries=[])  # 5 overdue
    add_order(
        db, boq, user, supplier, expected=ON - timedelta(days=20),
        deliveries=[(ON - timedelta(days=20), "4"), (ON - timedelta(days=17), "6")],
    )  # fmt: skip  # completed 3 days late
    add_order(
        db, boq, user, supplier, expected=ON - timedelta(days=8), deliveries=[(ON - timedelta(days=9), "10")]
    )  # early
    add_order(db, boq, user, supplier, expected=ON + timedelta(days=3), deliveries=[])  # not due yet
    on_time = ON - timedelta(days=2)
    add_order(db, boq, user, supplier, expected=on_time, deliveries=[(on_time, "10")])  # on the day: not late

    built = feature_builder.build(db, boq.project, ON)

    assert built.values["late_deliveries_count"] == 3
    assert built.values["avg_lateness_days"] == pytest.approx(4.0)


def test_heavy_rain_days_in_the_next_two_weeks(db: Session, boq: Boq, mat_site: Site) -> None:
    for d in range(1, 15):
        add_forecast(db, mat_site, ON + timedelta(days=d), "12.5" if d in (2, 3, 9) else "4.0")
    add_forecast(db, mat_site, ON, "50")  # today does not count
    add_forecast(db, mat_site, ON + timedelta(days=15), "50")  # nor beyond 14 days
    db.commit()

    assert feature_builder.build(db, boq.project, ON).values["rain_days_next_14"] == 3


def test_a_short_forecast_is_scaled_to_two_weeks(db: Session, boq: Boq, mat_site: Site) -> None:
    for d in range(1, 8):
        add_forecast(
            db, mat_site, ON + timedelta(days=d), "10.0" if d in (1, 2) else "0"
        )  # 10 mm counts as heavy
    db.commit()

    built = feature_builder.build(db, boq.project, ON)

    assert built.values["rain_days_next_14"] == 4.0
    assert any("Only 7 forecast days" in n for n in built.notes)


def test_committed_cost_against_its_budgeted_value(
    db: Session, boq: Boq, buyer: Who, supplier: Supplier
) -> None:
    # Cement's budgeted rate is LKR 2,000 a bag; 10 bags ordered at 2,200 is 10% over.
    add_order(db, boq, buyer.user, supplier, expected=ON + timedelta(days=5), deliveries=[], price="2200")

    assert feature_builder.build(db, boq.project, ON).values["budget_variance_pct"] == pytest.approx(10.0)


def test_crew_and_missing_reports_over_the_last_14_days(db: Session, boq: Boq, se: Who) -> None:
    boq.project.planned_crew = 50
    add_report(db, boq.project, se.user, ON, 40)
    add_report(
        db, boq.project, se.user, ON - timedelta(days=1), 35
    )  # Sunday: filed anyway, still counts for crew
    add_report(db, boq.project, se.user, ON - timedelta(days=2), 45)
    add_report(db, boq.project, se.user, ON - timedelta(days=20), 5)  # outside the window
    db.commit()

    built = feature_builder.build(db, boq.project, ON)

    assert built.values["crew_vs_plan_pct"] == pytest.approx(-20.0)
    # 14 days ending Monday 6 July hold 12 working days; reports cover two of them (Mon 6, Sat 4).
    assert built.values["missing_reports_14"] == 10


def test_missing_inputs_are_neutral_and_noted(db: Session, boq: Boq) -> None:
    built = feature_builder.build(db, boq.project, ON)

    assert built.values["progress_gap_pct"] == 0
    assert built.values["crew_vs_plan_pct"] == 0
    assert built.values["rain_days_next_14"] == 0
    assert built.values["missing_reports_14"] == 12  # nothing filed is itself a signal (BR-07)
    assert " ".join(built.notes).count("No ") == 3  # programme, planned crew, forecast
    assert built.values["contract_value_m"] == 10.0
    assert [k for k in FEATURE_NAMES if k.startswith("type_") and built.values[k]] == ["type_residential"]


def test_a_project_not_started_scores_on_size_and_type(db: Session, boq: Boq) -> None:
    built = feature_builder.build(db, boq.project, boq.project.start_date - timedelta(days=30))

    assert built.values["elapsed_pct"] == 0
    assert built.values["missing_reports_14"] == 0
    assert any("Not started" in n for n in built.notes)
    assert len(built.vector()) == len(FEATURE_NAMES)


# --- Scoring and BR-10 ----------------------------------------------------------------------------------


def high_risk(db: Session, project: Project) -> None:
    add_task(db, project, "0")  # nothing done half a year in: far behind plan


def notes_of(db: Session, user: User, kind: str = "risk_high") -> list[Notification]:
    return list(
        db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.kind == kind))
    )


def test_scoring_stores_the_forecast_with_drivers_and_inputs(db: Session, boq: Boq) -> None:
    high_risk(db, boq.project)

    result = risk_service.score_project(db, boq.project, ON, fake_model())

    row = db.scalar(select(RiskScore).where(RiskScore.project_id == boq.project.id))
    assert row is not None
    assert (row.score, row.level, result.level) == (100, "high", "high")
    assert row.delay_days == Decimal("200.0")
    assert row.model_version == "9.9.9"
    assert row.drivers[0]["feature"] == "progress_gap_pct"
    assert row.drivers[0]["delay_days"] == 150.0  # from the base of 50 to 200 days
    assert "behind" in row.drivers[0]["value"]
    assert set(row.features["values"]) == set(FEATURE_NAMES)
    assert row.score_date == ON


def test_rescoring_the_same_day_replaces_the_row(db: Session, boq: Boq) -> None:
    risk_service.score_project(db, boq.project, ON, fake_model())
    add_task(db, boq.project, "0")

    risk_service.score_project(db, boq.project, ON, fake_model())

    rows = db.scalars(select(RiskScore).where(RiskScore.project_id == boq.project.id)).all()
    assert len(rows) == 1
    assert rows[0].level == "high"


def test_br10_alerts_the_project_managers_when_a_project_enters_high(
    db: Session, boq: Boq, pm: Who, qs: Who, team: Callable[..., Who], make_site: Callable[..., Site]
) -> None:
    elsewhere = team(Role.PROJECT_MANAGER, sites=[make_site("KDY-09")])
    high_risk(db, boq.project)

    result = risk_service.score_project(db, boq.project, ON, fake_model())

    assert result.alerted is True
    [note] = notes_of(db, pm.user)
    assert note.title == "HR-1 is now high risk (100)"
    assert "progress against plan" in note.body
    assert note.link == f"/projects/{boq.project.id}"
    assert notes_of(db, qs.user) == []  # BR-10 alerts the PM
    assert notes_of(db, elsewhere.user) == []  # only on the project's site


def test_br10_does_not_repeat_while_the_project_stays_high(db: Session, boq: Boq, pm: Who) -> None:
    high_risk(db, boq.project)
    risk_service.score_project(db, boq.project, ON, fake_model())

    again_today = risk_service.score_project(db, boq.project, ON, fake_model())
    tomorrow = risk_service.score_project(db, boq.project, ON + timedelta(days=1), fake_model())

    assert (again_today.alerted, tomorrow.alerted) == (False, False)
    assert len(notes_of(db, pm.user)) == 1


def test_br10_alerts_again_after_the_project_recovers(db: Session, boq: Boq, pm: Who) -> None:
    task = add_task(db, boq.project, "0")
    risk_service.score_project(db, boq.project, ON, fake_model())
    task.percent_complete = Decimal("100")
    db.commit()
    assert risk_service.score_project(db, boq.project, ON + timedelta(days=1), fake_model()).level == "low"
    task.percent_complete = Decimal("0")
    db.commit()

    back = risk_service.score_project(db, boq.project, ON + timedelta(days=2), fake_model())

    assert back.alerted is True
    assert len(notes_of(db, pm.user)) == 2


def test_medium_risk_does_not_alert(db: Session, boq: Boq, pm: Who) -> None:
    high_risk(db, boq.project)

    result = risk_service.score_project(db, boq.project, ON, fake_model(delay_when_behind=100))

    assert (result.level, result.alerted) == ("medium", False)
    assert notes_of(db, pm.user) == []


def test_score_all_skips_closed_projects_and_survives_a_failure(
    db: Session,
    boq: Boq,
    make_site: Callable[..., Site],
    monkeypatch: pytest.MonkeyPatch,
    site_today: Callable[[date], None],
) -> None:
    site_today(ON)
    other_site = make_site("GAL-21")
    broken = Project(
        code="BR-1", name="Broken", site_id=other_site.id, client_name="C", project_type="commercial",
        status="active",
        contract_value=Decimal("5000000"), start_date=date(2026, 1, 5), planned_end=date(2026, 12, 31),
    )  # fmt: skip
    done = Project(
        code="DN-1", name="Done", site_id=other_site.id, client_name="C", project_type="commercial",
        status="completed", contract_value=Decimal("5000000"), start_date=date(2025, 1, 5),
        planned_end=date(2025, 12, 31),
    )  # fmt: skip
    db.add_all([broken, done])
    db.commit()
    real_build = feature_builder.build

    def build(session: Session, project: Project, on: date) -> feature_builder.FeatureSet:
        if project.code == "BR-1":
            raise RuntimeError("bad data")
        return real_build(session, project, on)

    monkeypatch.setattr(feature_builder, "build", build)

    results = risk_service.score_all(db)

    assert [r.project_id for r in results] == [boq.project.id]  # broken skipped, completed not scored


def test_the_shipped_model_scores_a_live_project(db: Session, boq: Boq) -> None:
    add_task(db, boq.project, "20")

    result = risk_service.score_project(db, boq.project, ON)

    row = db.scalar(select(RiskScore).where(RiskScore.project_id == boq.project.id))
    assert row is not None
    assert 0 <= row.score <= 100
    assert row.model_version == risk_model.CURRENT_VERSION
    assert result.score == row.score


# --- Endpoints --------------------------------------------------------------------------------------------


def test_pm_reads_the_latest_forecast_and_two_weeks_of_history(
    api: TestClient, db: Session, boq: Boq, pm: Who, site_today: Callable[[date], None]
) -> None:
    site_today(ON)
    high_risk(db, boq.project)
    for days_ago in (20, 3, 0):  # 20 days ago is outside the 14-day history
        risk_service.score_project(db, boq.project, ON - timedelta(days=days_ago), fake_model())

    response = api.get(f"/api/v1/projects/{boq.project.id}/risk", headers=pm.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["latest"]["score"] == 100
    assert body["latest"]["level"] == "high"
    assert body["latest"]["model_version"] == "9.9.9"
    assert body["latest"]["drivers"][0]["label"] == "Progress against plan"
    assert "No planned crew size set: crew counts as on plan." in body["latest"]["notes"]
    assert [p["date"] for p in body["history"]] == [(ON - timedelta(days=3)).isoformat(), ON.isoformat()]


def test_an_unscored_project_has_no_forecast_yet(api: TestClient, boq: Boq, qs: Who) -> None:
    body = api.get(f"/api/v1/projects/{boq.project.id}/risk", headers=qs.headers).json()

    assert body == {"project_id": str(boq.project.id), "latest": None, "history": []}


@pytest.mark.parametrize("role", [Role.SITE_ENGINEER, Role.PROCUREMENT_OFFICER, Role.CLIENT, Role.ADMIN])
def test_only_pm_and_qs_read_risk(api: TestClient, boq: Boq, team: Callable[..., Who], role: Role) -> None:
    who = team(role)

    assert api.get(f"/api/v1/projects/{boq.project.id}/risk", headers=who.headers).status_code == 403
    assert api.get("/api/v1/risk/projects", headers=who.headers).status_code == 403


def test_risk_on_other_sites_is_invisible(
    api: TestClient, db: Session, boq: Boq, team: Callable[..., Who], make_site: Callable[..., Site]
) -> None:
    risk_service.score_project(db, boq.project, ON, fake_model())
    outsider = team(Role.PROJECT_MANAGER, sites=[make_site("JAF-01")])

    assert api.get(f"/api/v1/projects/{boq.project.id}/risk", headers=outsider.headers).status_code == 404
    assert api.get(f"/api/v1/projects/{uuid.uuid4()}/risk", headers=outsider.headers).status_code == 404
    assert api.get("/api/v1/risk/projects", headers=outsider.headers).json() == []


def test_ranking_puts_the_riskiest_first_and_unscored_last(
    api: TestClient, db: Session, boq: Boq, pm: Who, mat_site: Site
) -> None:
    def project(code: str, status: str = "active") -> Project:
        p = Project(
            code=code, name=f"Project {code}", site_id=mat_site.id, client_name="C",
            project_type="commercial",
            status=status, contract_value=Decimal("5000000"), start_date=date(2026, 1, 5),
            planned_end=date(2027, 12, 31),
        )  # fmt: skip
        db.add(p)
        db.commit()
        return p

    calm, unscored, closed = project("CALM-1"), project("NEW-1"), project("OLD-1", "completed")
    high_risk(db, boq.project)
    risk_service.score_project(db, boq.project, ON, fake_model())
    risk_service.score_project(db, calm, ON - timedelta(days=1), fake_model())
    risk_service.score_project(db, calm, ON, fake_model())
    risk_service.score_project(db, closed, ON, fake_model())

    body = api.get("/api/v1/risk/projects", headers=pm.headers).json()

    assert [r["code"] for r in body] == ["HR-1", "CALM-1", "NEW-1"]  # closed projects are not ranked
    assert (body[0]["level"], body[0]["score"], body[0]["site_code"]) == ("high", 100, "COL-07")
    assert body[0]["top_driver"].startswith("Progress against plan: ")
    assert body[1]["score_date"] == ON.isoformat()  # the latest score, not an older one
    assert body[1]["top_driver"] is None  # nothing pushes the calm project's forecast up
    assert (body[2]["score"], body[2]["level"]) == (None, None)
    assert unscored.code == "NEW-1"


def test_filing_a_daily_report_rescores_the_project(
    api: TestClient, db: Session, report_project: Project, engineer: object
) -> None:
    response = api.post(
        f"/api/v1/projects/{report_project.id}/reports",
        json=report_body(),
        headers=engineer.headers,  # type: ignore[attr-defined]
    )

    assert response.status_code == 201, response.text
    rows = db.scalars(select(RiskScore).where(RiskScore.project_id == report_project.id)).all()
    assert [r.score_date for r in rows] == [clock.site_today()]


def test_a_scoring_failure_never_fails_the_report(
    api: TestClient, db: Session, report_project: Project, engineer: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(risk_service, "score_project", broken)

    response = api.post(
        f"/api/v1/projects/{report_project.id}/reports",
        json=report_body(),
        headers=engineer.headers,  # type: ignore[attr-defined]
    )

    assert response.status_code == 201
    assert db.scalar(select(func.count(RiskScore.id))) == 0
