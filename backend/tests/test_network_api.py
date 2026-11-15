"""Phase 9: dependencies, the critical path and forecast, working calendar, BR-06 (TC-12) and BR-11.

The calendar is controlled here: the project works Monday to Friday, holidays are cleared unless a
test adds one, and "today" is pinned. 5 January 2026 is a Monday.
"""

import itertools
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.permissions import Role
from app.models import (
    AuditLog,
    DailyReport,
    Holiday,
    Notification,
    Project,
    ReportAction,
    ReportActionTask,
    RiskScore,
    Site,
    Task,
    TaskDependency,
    User,
    WeatherForecast,
)
from app.schemas.schedule import NetworkOut
from app.services import network_service
from tests.conftest import bearer, login

D = Decimal
TODAY = date(2026, 1, 14)  # a Wednesday


@pytest.fixture(autouse=True)
def pinned(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    monkeypatch.setattr(clock, "site_today", lambda: TODAY)
    db.execute(delete(Holiday))
    db.commit()


@pytest.fixture
def site(make_site: Callable[..., Site]) -> Site:
    return make_site("COL-07")


@pytest.fixture
def project(db: Session, site: Site) -> Project:
    p = Project(
        code="NET-1", name="Network", site_id=site.id, client_name="Client", project_type="residential",
        status="active", contract_value=D("1000000.00"), start_date=date(2026, 1, 5),
        planned_end=date(2026, 1, 30), working_week="12345",
    )  # fmt: skip
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def pm_user(make_user: Callable[..., User], site: Site) -> User:
    return make_user(Role.PROJECT_MANAGER, sites=[site])


@pytest.fixture
def pm(api: TestClient, pm_user: User) -> dict[str, str]:
    return bearer(login(api, pm_user.email))


@pytest.fixture
def engineer_user(make_user: Callable[..., User], site: Site) -> User:
    return make_user(Role.SITE_ENGINEER, sites=[site])


@pytest.fixture
def engineer(api: TestClient, engineer_user: User) -> dict[str, str]:
    return bearer(login(api, engineer_user.email))


def task(
    db: Session, project: Project, code: str, start: date, end: date, pct: str = "0", **extra: object
) -> Task:
    position = len(db.scalars(select(Task).where(Task.project_id == project.id)).all()) + 1
    row = Task(project_id=project.id, code=code, name=f"Task {code}", planned_start=start, planned_end=end,
               weight=D("10"), percent_complete=D(pct), position=position, **extra)  # fmt: skip
    db.add(row)
    db.commit()
    return row


def link(api: TestClient, project: Project, headers: dict[str, str], before: Task, after: Task, lag: int = 0):  # type: ignore[no-untyped-def]
    return api.post(
        f"/api/v1/projects/{project.id}/dependencies",
        json={"predecessor_id": str(before.id), "successor_id": str(after.id), "lag_days": lag},
        headers=headers,
    )


def network(api: TestClient, project: Project, headers: dict[str, str]) -> dict:  # type: ignore[type-arg]
    response = api.get(f"/api/v1/projects/{project.id}/network", headers=headers)
    assert response.status_code == 200, response.text
    body: dict = response.json()  # type: ignore[type-arg]
    return body


def by_code(net: dict) -> dict[str, dict]:  # type: ignore[type-arg]
    return {t["code"]: t for t in net["tasks"]}


# --- Dependencies and the critical path ----------------------------------------------------------------


def textbook(db: Session, project: Project) -> dict[str, Task]:
    """A(3) -> B(2), A -> C(4), B and C -> D(1), all planned from Monday 5 January, none started."""
    return {
        "A": task(db, project, "A", date(2026, 1, 5), date(2026, 1, 7)),
        "B": task(db, project, "B", date(2026, 1, 5), date(2026, 1, 6)),
        "C": task(db, project, "C", date(2026, 1, 5), date(2026, 1, 8)),
        "D": task(db, project, "D", date(2026, 1, 5), date(2026, 1, 5)),
    }


def test_the_pm_links_tasks_and_the_network_finds_the_critical_path(
    api: TestClient, db: Session, project: Project, pm: dict[str, str]
) -> None:
    t = textbook(db, project)
    for before, after in (("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")):
        assert link(api, project, pm, t[before], t[after]).status_code == 201

    net = network(api, project, pm)
    tasks = by_code(net)

    assert net["network_end"] == "2026-01-14"  # the plan through its links: A Mon-Wed, C Thu-Tue, D Wed
    assert {c: tasks[c]["total_float"] for c in "ABCD"} == {"A": 0, "B": 2, "C": 0, "D": 0}
    # Nothing started and today is Wednesday 14th: the forecast starts A today.
    assert (tasks["A"]["forecast_start"], tasks["D"]["forecast_finish"]) == ("2026-01-14", "2026-01-23")
    assert [c for c in "ABCD" if tasks[c]["is_critical"]] == ["A", "C", "D"]
    assert sorted(tasks["D"]["predecessors"]) == sorted([str(t["B"].id), str(t["C"].id)])
    assert db.scalar(select(AuditLog).where(AuditLog.action == "task.dependency_added")) is not None
    listed = api.get(f"/api/v1/projects/{project.id}/tasks", headers=pm).json()["tasks"]
    assert [x["code"] for x in listed if x["is_critical"]] == ["A", "C", "D"]


def test_a_loop_is_refused(api: TestClient, db: Session, project: Project, pm: dict[str, str]) -> None:
    t = textbook(db, project)
    link(api, project, pm, t["A"], t["B"])
    link(api, project, pm, t["B"], t["D"])

    loop = link(api, project, pm, t["D"], t["A"])
    duplicate = link(api, project, pm, t["A"], t["B"])
    itself = api.post(
        f"/api/v1/projects/{project.id}/dependencies",
        json={"predecessor_id": str(t["A"].id), "successor_id": str(t["A"].id)},
        headers=pm,
    )

    assert loop.status_code == 422
    assert loop.json()["error"]["code"] == "dependency_loop"
    assert duplicate.status_code == 409
    assert itself.status_code == 422


def test_a_programme_has_a_link_limit(
    api: TestClient, db: Session, project: Project, pm: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(network_service, "MAX_LINKS_PER_PROJECT", 1)
    t = textbook(db, project)
    assert link(api, project, pm, t["A"], t["B"]).status_code == 201

    refused = link(api, project, pm, t["A"], t["C"])

    assert refused.status_code == 422
    assert "at most 1 links" in refused.json()["error"]["message"]


def test_links_stay_inside_one_project(
    api: TestClient, db: Session, project: Project, site: Site, pm: dict[str, str]
) -> None:
    other = Project(
        code="NET-2", name="Other", site_id=site.id, client_name="C", project_type="residential",
        status="active", contract_value=D("1000.00"), start_date=date(2026, 1, 5),
        planned_end=date(2026, 2, 27),
    )  # fmt: skip
    db.add(other)
    db.commit()
    mine = task(db, project, "A", date(2026, 1, 5), date(2026, 1, 9))
    theirs = task(db, other, "X", date(2026, 1, 5), date(2026, 1, 9))

    response = link(api, project, pm, mine, theirs)

    assert response.status_code == 422
    assert "this project's programme" in response.json()["error"]["message"]


def test_removing_a_link(
    api: TestClient, db: Session, project: Project, pm: dict[str, str], engineer: dict[str, str]
) -> None:
    t = textbook(db, project)
    dep = link(api, project, pm, t["A"], t["B"], lag=2).json()
    assert dep["lag_days"] == 2

    assert api.delete(f"/api/v1/dependencies/{dep['id']}", headers=engineer).status_code == 403
    assert api.delete(f"/api/v1/dependencies/{dep['id']}", headers=pm).status_code == 204
    assert api.delete(f"/api/v1/dependencies/{dep['id']}", headers=pm).status_code == 404
    assert network(api, project, pm)["dependencies"] == []


def test_links_on_another_site_are_invisible(
    api: TestClient, db: Session, project: Project, pm: dict[str, str], make_user: Callable[..., User],
    make_site: Callable[..., Site],
) -> None:  # fmt: skip
    t = textbook(db, project)
    dep = link(api, project, pm, t["A"], t["B"]).json()
    stranger = bearer(login(api, make_user(Role.PROJECT_MANAGER, sites=[make_site("KDY-01")]).email))

    assert api.delete(f"/api/v1/dependencies/{dep['id']}", headers=stranger).status_code == 404
    assert api.get(f"/api/v1/projects/{project.id}/network", headers=stranger).status_code == 404


# --- Forecast ------------------------------------------------------------------------------------------


def test_the_forecast_follows_the_rate_so_far_and_shows_slip(
    api: TestClient, db: Session, project: Project, pm: dict[str, str]
) -> None:
    """A started Monday 5th, 40% after 8 working days (to Wed 14th): 5% a day, 60% left = 12 days."""
    a = task(db, project, "A", date(2026, 1, 5), date(2026, 1, 16), pct="40", actual_start=date(2026, 1, 5))
    b = task(db, project, "B", date(2026, 1, 19), date(2026, 1, 30))
    link(api, project, pm, a, b)

    net = network(api, project, pm)
    tasks = by_code(net)

    assert tasks["A"]["forecast_finish"] == "2026-01-30"  # Thu 15th + 12 working days - 1
    assert tasks["A"]["slip_days"] == 10
    assert tasks["B"]["forecast_start"] == "2026-02-02"
    assert net["forecast_end"] == "2026-02-13"
    assert net["slip_days"] == 10
    assert tasks["A"]["is_critical"]
    assert tasks["B"]["is_critical"]


def test_done_work_keeps_its_dates_and_is_not_critical(
    api: TestClient, db: Session, project: Project, pm: dict[str, str]
) -> None:
    task(db, project, "A", date(2026, 1, 5), date(2026, 1, 9), pct="100",
         actual_start=date(2026, 1, 5), actual_finish=date(2026, 1, 8))  # fmt: skip

    [a] = network(api, project, pm)["tasks"]

    assert (a["forecast_start"], a["forecast_finish"], a["is_done"], a["is_critical"]) == (
        "2026-01-05",
        "2026-01-08",
        True,
        False,
    )


def test_the_working_week_and_holidays_shape_the_dates(
    api: TestClient, db: Session, project: Project, pm: dict[str, str]
) -> None:
    # Planned Mon 12 - Fri 16 (5 working days), not started: the forecast starts today, Wednesday 14.
    task(db, project, "A", date(2026, 1, 12), date(2026, 1, 16))
    assert by_code(network(api, project, pm))["A"]["forecast_finish"] == "2026-01-20"  # 14, 15, 16, 19, 20
    db.add(Holiday(holiday_date=date(2026, 1, 19), name="Test Poya", created_at=clock.utcnow()))
    db.commit()

    assert by_code(network(api, project, pm))["A"]["forecast_finish"] == "2026-01-21"  # Monday 19 skipped
    assert (
        api.patch(f"/api/v1/projects/{project.id}", json={"working_week": "654321"}, headers=pm).json()[
            "working_week"
        ]
        == "123456"
    )
    assert by_code(network(api, project, pm))["A"]["forecast_finish"] == "2026-01-20"  # Saturday 17 works now


def test_a_network_past_the_calendar_horizon_still_loads(
    api: TestClient, db: Session, project: Project, pm_user: User, pm: dict[str, str]
) -> None:
    """25 tasks chained with a year's lag each run past 30 years: shown on their own dates, with a warning."""
    chain = [task(db, project, f"T{i:02}", date(2026, 1, 5), date(2026, 1, 9)) for i in range(25)]
    for before, after in itertools.pairwise(chain):
        db.add(TaskDependency(project_id=project.id, predecessor_id=before.id, successor_id=after.id,
                              lag_days=365, created_by=pm_user.id, created_at=clock.utcnow()))  # fmt: skip
    db.commit()

    net = network(api, project, pm)
    listed = api.get(f"/api/v1/projects/{project.id}/tasks", headers=pm)

    assert "more than 30 years out" in net["warnings"][0]
    assert {(t["forecast_finish"], t["is_critical"]) for t in net["tasks"]} == {("2026-01-09", False)}
    assert listed.status_code == 200


@pytest.mark.parametrize("week", ["", "1234567x", "1123", "8"])
def test_a_working_week_is_validated(
    api: TestClient, project: Project, pm: dict[str, str], week: str
) -> None:
    assert (
        api.patch(f"/api/v1/projects/{project.id}", json={"working_week": week}, headers=pm).status_code
        == 422
    )


def test_a_year_without_holidays_is_warned_about(
    api: TestClient, db: Session, project: Project, pm: dict[str, str]
) -> None:
    task(db, project, "A", date(2026, 1, 5), date(2026, 1, 9))

    warnings = network(api, project, pm)["warnings"]

    assert len(warnings) == 1
    assert "No holidays are entered for 2026" in warnings[0]


# --- BR-11: stop-work stops tasks --------------------------------------------------------------------


def stop(
    db: Session, project: Project, author: User, scope: str, tasks: list[Task], since: date
) -> ReportAction:
    at = datetime.combine(since, datetime.min.time(), clock.site_zone())
    report = DailyReport(
        project_id=project.id, author_id=author.id, report_date=since, crew_count=5,
        work_done="Work on site today.", submitted_at=at,
    )  # fmt: skip
    db.add(report)
    db.flush()
    flag = ReportAction(
        report_id=report.id, project_id=project.id, kind="stop_work", status="open", summary="Helper fell",
        created_by=author.id, created_at=at,
        stop_scope=scope,
    )  # fmt: skip
    flag.stop_tasks = [ReportActionTask(task_id=t.id) for t in tasks]
    db.add(flag)
    db.commit()
    return flag


def test_br11_a_stopped_task_takes_no_progress_until_the_pm_clears_it(
    api: TestClient,
    db: Session,
    project: Project,
    pm: dict[str, str],
    engineer: dict[str, str],
    engineer_user: User,
) -> None:
    a = task(db, project, "A", date(2026, 1, 5), date(2026, 1, 16), pct="20", actual_start=date(2026, 1, 5))
    b = task(db, project, "B", date(2026, 1, 5), date(2026, 1, 16), pct="20", actual_start=date(2026, 1, 5))
    flag = stop(db, project, engineer_user, "tasks", [a], TODAY)

    refused = api.patch(f"/api/v1/tasks/{a.id}", json={"percent_complete": "30"}, headers=engineer)
    allowed = api.patch(f"/api/v1/tasks/{b.id}", json={"percent_complete": "30"}, headers=engineer)
    tasks = by_code(network(api, project, pm))

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "stop_work"
    assert allowed.status_code == 200
    assert (tasks["A"]["stopped"], tasks["B"]["stopped"]) == (True, False)
    cleared = api.post(f"/api/v1/report-actions/{flag.id}/close", json={"resolution": "done"}, headers=pm)
    assert cleared.status_code == 200
    assert (
        api.patch(f"/api/v1/tasks/{a.id}", json={"percent_complete": "30"}, headers=engineer).status_code
        == 200
    )
    assert db.scalar(select(RiskScore).where(RiskScore.project_id == project.id)) is not None  # re-scored


def test_br11_the_whole_project_stops_daily_report_progress_too(
    api: TestClient, db: Session, project: Project, engineer: dict[str, str], engineer_user: User
) -> None:
    a = task(db, project, "A", date(2026, 1, 5), date(2026, 1, 16))
    stop(db, project, engineer_user, "project", [], TODAY - timedelta(days=1))

    response = api.post(
        f"/api/v1/projects/{project.id}/reports",
        json={"report_date": TODAY.isoformat(), "crew_count": 3, "work_done": "Cleared the slab area.",
              "progress": [{"task_id": str(a.id), "percent_complete": "10"}]},
        headers=engineer,
    )  # fmt: skip

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "stop_work"


def test_br11_each_stopped_working_day_moves_the_forecast_one_working_day(
    db: Session, project: Project, engineer_user: User
) -> None:
    a = task(db, project, "A", date(2026, 1, 5), date(2026, 1, 16), pct="40", actual_start=date(2026, 1, 5))
    stop(db, project, engineer_user, "tasks", [a], date(2026, 1, 13))  # stopped since Tuesday

    wednesday = network_service.analyse(db, project, today=date(2026, 1, 14))
    thursday = network_service.analyse(db, project, today=date(2026, 1, 15))
    monday = network_service.analyse(db, project, today=date(2026, 1, 19))

    def finish(net: NetworkOut) -> date:
        return next(t.forecast_finish for t in net.tasks)

    # 40% in 6 working days before the stop: rate 40/6; 60% left = 9 days, starting the next working day.
    assert [t.stopped_days for t in wednesday.tasks] == [2]
    assert finish(thursday) == finish(wednesday) + timedelta(days=1)
    # Two more stopped working days (Friday and Monday) move it two working days: Wed 28 to Fri 30.
    assert finish(monday) == finish(thursday) + timedelta(days=2)


def test_br11_a_cleared_flag_stops_counting_from_the_day_it_is_cleared(
    db: Session, project: Project, engineer_user: User
) -> None:
    a = task(db, project, "A", date(2026, 1, 5), date(2026, 1, 16), pct="40", actual_start=date(2026, 1, 5))
    flag = stop(db, project, engineer_user, "tasks", [a], date(2026, 1, 13))  # Tuesday
    flag.status = "done"
    flag.closed_at = datetime.combine(date(2026, 1, 15), datetime.min.time(), clock.site_zone())  # Thu
    db.commit()

    monday = network_service.analyse(db, project, today=date(2026, 1, 19))

    # Stopped Tuesday and Wednesday only; the flag was cleared on Thursday.
    assert [(t.stopped, t.stopped_days) for t in monday.tasks] == [(False, 2)]


def test_br11_two_flags_on_the_same_days_count_them_once(
    db: Session, project: Project, engineer_user: User
) -> None:
    a = task(db, project, "A", date(2026, 1, 5), date(2026, 1, 16), pct="40", actual_start=date(2026, 1, 5))
    stop(db, project, engineer_user, "tasks", [a], date(2026, 1, 13))  # Tuesday
    stop(db, project, engineer_user, "project", [], date(2026, 1, 14))  # Wednesday, still open

    friday = network_service.analyse(db, project, today=date(2026, 1, 16))

    assert [t.stopped_days for t in friday.tasks] == [4]  # Tue to Fri, not 4 + 3


def test_br11_the_author_chooses_the_scope_and_the_pm_can_change_it(
    api: TestClient,
    db: Session,
    project: Project,
    pm: dict[str, str],
    engineer: dict[str, str],
    engineer_user: User,
) -> None:
    a = task(db, project, "A", date(2026, 1, 5), date(2026, 1, 16))
    b = task(db, project, "B", date(2026, 1, 5), date(2026, 1, 16))
    flag = stop(db, project, engineer_user, "tasks", [a], TODAY)
    url = f"/api/v1/report-actions/{flag.id}/stop-scope"

    assert api.put(url, json={"scope": "tasks", "task_ids": [str(b.id)]}, headers=engineer).status_code == 403
    assert api.put(url, json={"scope": "tasks", "task_ids": []}, headers=pm).status_code == 422
    changed = api.put(url, json={"scope": "tasks", "task_ids": [str(a.id), str(b.id)]}, headers=pm).json()
    assert (changed["stop_scope"], sorted(changed["stop_task_ids"])) == (
        "tasks",
        sorted([str(a.id), str(b.id)]),
    )
    whole = api.put(url, json={"scope": "project"}, headers=pm).json()
    assert (whole["stop_scope"], whole["stop_task_ids"]) == ("project", [])
    assert (
        db.scalar(select(AuditLog).where(AuditLog.action == "report_action.stop_scope_changed")) is not None
    )
    api.post(f"/api/v1/report-actions/{flag.id}/close", json={"resolution": "done"}, headers=pm)
    assert api.put(url, json={"scope": "project"}, headers=pm).status_code == 409


# --- BR-06 / TC-12: pours on heavy-rain days -----------------------------------------------------------


def rain(db: Session, site: Site, day: date, mm: str) -> None:
    db.add(
        WeatherForecast(
            site_id=site.id, forecast_date=day, summary="Rain", rain_mm=D(mm), fetched_at=clock.utcnow()
        )
    )
    db.commit()


def test_tc12_heavy_rain_on_a_pour_day_flags_the_task_and_alerts_the_pm(
    api: TestClient, db: Session, project: Project, site: Site, pm: dict[str, str], pm_user: User
) -> None:
    pour = task(db, project, "P", date(2026, 1, 19), date(2026, 1, 21), is_concrete_pour=True)
    task(db, project, "Q", date(2026, 1, 19), date(2026, 1, 21))  # same days, not a pour
    rain(db, site, date(2026, 1, 20), "10.0")  # exactly 10 mm counts (BR-06: 10 mm or more)
    rain(db, site, date(2026, 1, 21), "9.9")
    rain(db, site, date(2026, 1, 24), "40")  # Saturday: not a working day here

    tasks = by_code(network(api, project, pm))
    sent = network_service.check_pours(db, project)
    db.commit()
    again = network_service.check_pours(db, project)

    assert tasks["P"]["rain_days"] == ["2026-01-20"]
    assert tasks["Q"]["rain_days"] == []
    assert (sent, again) == (1, 0)  # once per task and set of rain days
    [note] = db.scalars(
        select(Notification).where(Notification.user_id == pm_user.id, Notification.kind == "pour_rain")
    )
    assert "20 Jan" in note.body
    assert pour.id is not None


def test_a_new_rain_day_alerts_again_and_done_pours_are_left_alone(
    db: Session, project: Project, site: Site, pm_user: User
) -> None:
    task(db, project, "P", date(2026, 1, 19), date(2026, 1, 23), is_concrete_pour=True)
    task(db, project, "R", date(2026, 1, 5), date(2026, 1, 9), pct="100", is_concrete_pour=True,
         actual_start=date(2026, 1, 5), actual_finish=date(2026, 1, 9))  # fmt: skip
    rain(db, site, date(2026, 1, 20), "15")
    assert network_service.check_all_pours(db) == 1
    rain(db, site, date(2026, 1, 22), "30")

    assert network_service.check_all_pours(db) == 1
    assert len(db.scalars(select(Notification).where(Notification.kind == "pour_rain")).all()) == 2


def test_marking_a_task_as_a_pour_checks_the_weather(
    api: TestClient, db: Session, project: Project, site: Site, pm: dict[str, str], pm_user: User
) -> None:
    rain(db, site, date(2026, 1, 20), "25")
    created = api.post(
        f"/api/v1/projects/{project.id}/tasks",
        json={"name": "Slab pour", "planned_start": "2026-01-19", "planned_end": "2026-01-20", "weight": "5",
              "is_concrete_pour": True},
        headers=pm,
    )  # fmt: skip

    assert created.json()["is_concrete_pour"] is True
    assert db.scalar(select(Notification).where(Notification.kind == "pour_rain")) is not None


# --- Holidays: Company Admin ----------------------------------------------------------------------------


def test_the_admin_keeps_the_holiday_list_and_is_warned_about_next_year(
    api: TestClient, db: Session, make_user: Callable[..., User], pm: dict[str, str]
) -> None:
    admin = bearer(login(api, make_user(Role.ADMIN).email))
    body = {"holiday_date": "2026-12-25", "name": "Christmas Day"}

    assert api.post("/api/v1/admin/holidays", json=body, headers=pm).status_code == 403
    created = api.post("/api/v1/admin/holidays", json=body, headers=admin)
    assert created.status_code == 201
    assert api.post("/api/v1/admin/holidays", json=body, headers=admin).status_code == 409
    far = {"holiday_date": "2999-01-01", "name": "Far future"}
    assert api.post("/api/v1/admin/holidays", json=far, headers=admin).status_code == 422
    listing = api.get("/api/v1/admin/holidays", headers=admin).json()
    assert (listing["years"], listing["missing_next_year"]) == ([2026], True)
    assert api.delete(f"/api/v1/admin/holidays/{created.json()['id']}", headers=admin).status_code == 204
    assert api.delete(f"/api/v1/admin/holidays/{created.json()['id']}", headers=admin).status_code == 404
    actions = {a.action for a in db.scalars(select(AuditLog).where(AuditLog.action.like("holiday.%")))}
    assert actions == {"holiday.added", "holiday.removed"}


def test_a_long_wet_spell_still_alerts(db: Session, project: Project, site: Site, pm_user: User) -> None:
    """Found in the browser check: nine rain days made the alert's key too long for its column."""
    task(db, project, "P", date(2026, 1, 15), date(2026, 1, 30), is_concrete_pour=True)
    for d in range(15, 31):
        rain(db, site, date(2026, 1, d), "20")

    assert network_service.check_pours(db, project) == 1
    db.commit()

    [note] = db.scalars(select(Notification).where(Notification.kind == "pour_rain"))
    assert "and 7 more days" in note.body  # 12 working days, five named
    assert len(note.dedupe_key or "") <= 120
