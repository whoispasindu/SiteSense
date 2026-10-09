from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.permissions import Role
from app.models import AuditLog, BoqSection, BudgetLine, ProgressSnapshot, Project, Site, Task, User
from tests.conftest import bearer, login


@pytest.fixture(autouse=True)
def today(monkeypatch: pytest.MonkeyPatch) -> Callable[[date], None]:
    """Pin the site's calendar date. Only the date moves; token clocks keep real time."""

    def set_today(day: date) -> None:
        monkeypatch.setattr(clock, "site_today", lambda: day)

    set_today(date(2026, 3, 15))
    return set_today


@pytest.fixture
def site(make_site: Callable[..., Site]) -> Site:
    return make_site("COL-07")


@pytest.fixture
def project(db: Session, site: Site) -> Project:
    p = Project(
        code="HR-1",
        name="Havelock",
        site_id=site.id,
        client_name="Client",
        project_type="residential",
        status="active",
        contract_value=Decimal("1000000.00"),
        start_date=date(2026, 3, 1),
        planned_end=date(2026, 3, 31),
    )
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def pm(api: TestClient, make_user: Callable[..., User], site: Site) -> dict[str, str]:
    return bearer(login(api, make_user(Role.PROJECT_MANAGER, sites=[site]).email))


@pytest.fixture
def engineer(api: TestClient, make_user: Callable[..., User], site: Site) -> dict[str, str]:
    return bearer(login(api, make_user(Role.SITE_ENGINEER, sites=[site]).email))


def tasks_url(project: Project) -> str:
    return f"/api/v1/projects/{project.id}/tasks"


def add_task(api: TestClient, project: Project, headers: dict[str, str], **body: object) -> dict[str, object]:
    payload = {
        "name": "Excavation",
        "planned_start": "2026-03-01",
        "planned_end": "2026-03-10",
        "weight": "30",
        **body,
    }
    response = api.post(tasks_url(project), json=payload, headers=headers)
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


# --- Creating tasks -------------------------------------------------------------------------


def test_pm_creates_tasks_with_computed_plan_state(
    api: TestClient, project: Project, pm: dict[str, str], today: Callable[[date], None], db: Session
) -> None:
    created = add_task(api, project, pm, code="t-010", percent_complete="20")

    assert created["code"] == "T-010"
    assert created["weight"] == "30.00"
    assert created["planned_percent_today"] == 100.0  # ended on 10 March; today is 15 March
    assert created["state"] == "behind"
    assert created["position"] == 1
    listed = api.get(tasks_url(project), headers=pm).json()
    assert listed["weight_total"] == "30.00"
    assert [t["name"] for t in listed["tasks"]] == ["Excavation"]
    db.expire_all()
    assert db.scalar(select(AuditLog.action).where(AuditLog.action == "task.created")) is not None


@pytest.mark.parametrize(
    "override",
    [
        {"planned_end": "2026-02-01"},
        {"weight": "0"},
        {"weight": "100.01"},
        {"weight": "12.345"},
        {"percent_complete": "101"},
        {"code": "bad code"},
        {"name": "x"},
        {"duration": 5},
    ],
)
def test_task_input_is_validated(
    api: TestClient, project: Project, pm: dict[str, str], override: dict[str, object]
) -> None:
    payload = {
        "name": "Excavation",
        "planned_start": "2026-03-01",
        "planned_end": "2026-03-10",
        "weight": "30",
    }

    assert api.post(tasks_url(project), json={**payload, **override}, headers=pm).status_code == 422


def test_business_rules_on_tasks(
    api: TestClient, project: Project, pm: dict[str, str], db: Session, site: Site
) -> None:
    other = Project(
        code="OTHER",
        name="Other",
        site_id=site.id,
        client_name="C",
        project_type="commercial",
        status="active",
        contract_value=Decimal("1.00"),
        start_date=date(2026, 1, 1),
        planned_end=date(2026, 12, 31),
    )
    db.add(other)
    db.flush()
    foreign_section = BoqSection(project_id=other.id, code="A", name="Prelims", position=1)
    foreign_section.budget_line = BudgetLine(project_id=other.id, budget_amount=Decimal("1.00"))
    db.add(foreign_section)
    db.commit()
    add_task(api, project, pm, code="T-1")
    base = {"name": "Piling", "planned_start": "2026-03-01", "planned_end": "2026-03-10", "weight": "10"}

    too_early = api.post(tasks_url(project), json={**base, "planned_start": "2026-02-20"}, headers=pm)
    wrong_section = api.post(
        tasks_url(project), json={**base, "boq_section_id": str(foreign_section.id)}, headers=pm
    )
    duplicate = api.post(tasks_url(project), json={**base, "code": "t-1"}, headers=pm)

    assert too_early.status_code == 422
    assert "before the project starts" in too_early.json()["error"]["message"]
    assert wrong_section.status_code == 422
    assert duplicate.status_code == 409


# --- Updating progress ----------------------------------------------------------------------


def test_engineer_reports_progress_but_cannot_replan(
    api: TestClient,
    project: Project,
    pm: dict[str, str],
    engineer: dict[str, str],
    db: Session,
    today: Callable[[date], None],
) -> None:
    task = add_task(api, project, pm)
    url = f"/api/v1/tasks/{task['id']}"

    progress = api.patch(url, json={"percent_complete": "45.5"}, headers=engineer)
    replan = api.patch(url, json={"percent_complete": "50", "weight": "90"}, headers=engineer)
    rename = api.patch(url, json={"name": "Renamed"}, headers=engineer)

    assert progress.status_code == 200
    assert progress.json()["percent_complete"] == "45.50"
    assert progress.json()["progress_updated_at"] is not None
    assert replan.status_code == rename.status_code == 403
    db.expire_all()
    assert db.get(Task, task["id"]).weight == Decimal("30.00")  # type: ignore[union-attr]
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "task.progress_updated"))
    assert entry is not None
    assert entry.details == {"from": "0.00", "to": "45.50"}


def test_pm_replans_a_task(api: TestClient, project: Project, pm: dict[str, str]) -> None:
    task = add_task(api, project, pm)
    url = f"/api/v1/tasks/{task['id']}"

    updated = api.patch(url, json={"planned_end": "2026-03-20", "is_critical": True}, headers=pm)
    backwards = api.patch(url, json={"planned_end": "2026-02-01"}, headers=pm)
    null_weight = api.patch(url, json={"weight": None}, headers=pm)

    assert updated.status_code == 200
    assert updated.json()["is_critical"] is True
    assert backwards.status_code == 422
    assert null_weight.status_code == 422


@pytest.mark.parametrize("role", [Role.QUANTITY_SURVEYOR, Role.CLIENT, Role.PROCUREMENT_OFFICER, Role.ADMIN])
def test_other_roles_cannot_touch_tasks(
    api: TestClient,
    project: Project,
    pm: dict[str, str],
    make_user: Callable[..., User],
    site: Site,
    role: Role,
) -> None:
    task = add_task(api, project, pm)
    headers = bearer(
        login(
            api, make_user(role, sites=[site] if role in (Role.QUANTITY_SURVEYOR, Role.CLIENT) else []).email
        )
    )

    assert (
        api.patch(f"/api/v1/tasks/{task['id']}", json={"percent_complete": "10"}, headers=headers).status_code
        == 403
    )
    assert api.delete(f"/api/v1/tasks/{task['id']}", headers=headers).status_code == 403


def test_tasks_on_other_sites_are_invisible(
    api: TestClient,
    project: Project,
    pm: dict[str, str],
    make_user: Callable[..., User],
    make_site: Callable[..., Site],
) -> None:
    task = add_task(api, project, pm)
    outsider = bearer(login(api, make_user(Role.SITE_ENGINEER, sites=[make_site("KDY-02")]).email))

    assert (
        api.patch(
            f"/api/v1/tasks/{task['id']}", json={"percent_complete": "10"}, headers=outsider
        ).status_code
        == 404
    )
    assert api.get(tasks_url(project), headers=outsider).status_code == 404
    assert api.get(f"/api/v1/projects/{project.id}/progress", headers=outsider).status_code == 404


def test_delete_task(api: TestClient, project: Project, pm: dict[str, str], engineer: dict[str, str]) -> None:
    task = add_task(api, project, pm)

    assert api.delete(f"/api/v1/tasks/{task['id']}", headers=engineer).status_code == 403
    assert api.delete(f"/api/v1/tasks/{task['id']}", headers=pm).status_code == 204
    assert api.get(tasks_url(project), headers=pm).json()["tasks"] == []
    assert api.delete(f"/api/v1/tasks/{task['id']}", headers=pm).status_code == 404


# --- Progress curve ("Done when") -----------------------------------------------------------


def test_s_curve_updates_when_tasks_change(
    api: TestClient,
    project: Project,
    pm: dict[str, str],
    engineer: dict[str, str],
    today: Callable[[date], None],
    db: Session,
) -> None:
    first = add_task(
        api,
        project,
        pm,
        name="Substructure",
        planned_start="2026-03-01",
        planned_end="2026-03-10",
        weight="40",
    )
    add_task(
        api, project, pm, name="Frame", planned_start="2026-03-11", planned_end="2026-03-30", weight="60"
    )
    progress_url = f"/api/v1/projects/{project.id}/progress"

    before = api.get(progress_url, headers=engineer).json()
    api.patch(f"/api/v1/tasks/{first['id']}", json={"percent_complete": "100"}, headers=engineer)
    after = api.get(progress_url, headers=engineer).json()

    assert before["as_of"] == "2026-03-15"
    assert before["planned_percent"] == 40 + 60 * 5 / 20  # Frame is 5 of 20 days in
    assert before["actual_percent"] == 0.0
    assert after["actual_percent"] == 40.0
    assert after["variance"] == round(40.0 - after["planned_percent"], 2)
    assert after["weight_total"] == "100.00"
    assert after["programme_start"] == "2026-03-01"
    assert after["contract_end"] == "2026-03-31"
    points = {p["date"]: p for p in after["points"]}
    assert points["2026-03-15"]["actual"] == 40.0  # today: live value
    assert points["2026-03-22"]["actual"] is None  # future
    assert points["2026-03-31"]["planned"] == 100.0
    db.expire_all()
    snapshots = db.scalars(select(ProgressSnapshot).where(ProgressSnapshot.project_id == project.id)).all()
    assert [(s.snapshot_date, s.actual_percent) for s in snapshots] == [(date(2026, 3, 15), Decimal("40.00"))]


def test_history_is_kept_one_snapshot_per_day(
    api: TestClient, project: Project, pm: dict[str, str], today: Callable[[date], None], db: Session
) -> None:
    task = add_task(api, project, pm, weight="100", planned_end="2026-03-31")
    url = f"/api/v1/tasks/{task['id']}"
    api.patch(url, json={"percent_complete": "10"}, headers=pm)
    api.patch(url, json={"percent_complete": "12"}, headers=pm)  # same day: replaces
    today(date(2026, 3, 22))
    api.patch(url, json={"percent_complete": "30"}, headers=pm)

    curve = api.get(f"/api/v1/projects/{project.id}/progress", headers=pm).json()["points"]

    db.expire_all()
    history = db.scalars(
        select(ProgressSnapshot)
        .where(ProgressSnapshot.project_id == project.id)
        .order_by(ProgressSnapshot.snapshot_date)
    ).all()
    assert [(s.snapshot_date.day, float(s.actual_percent)) for s in history] == [(15, 12.0), (22, 30.0)]
    by_day = {p["date"]: p["actual"] for p in curve}
    assert by_day["2026-03-15"] == 12.0
    assert by_day["2026-03-22"] == 30.0


def test_progress_with_no_tasks(api: TestClient, project: Project, pm: dict[str, str]) -> None:
    body = api.get(f"/api/v1/projects/{project.id}/progress", headers=pm).json()

    assert body["task_count"] == 0
    assert body["planned_percent"] == 0.0
    assert body["programme_end"] == "2026-03-31"


def test_schedule_summary_is_scoped(
    api: TestClient,
    project: Project,
    pm: dict[str, str],
    make_user: Callable[..., User],
    make_site: Callable[..., Site],
    today: Callable[[date], None],
) -> None:
    add_task(api, project, pm, weight="100", planned_end="2026-03-31", percent_complete="10")
    outsider = bearer(login(api, make_user(Role.SITE_ENGINEER, sites=[make_site("GAL-11")]).email))

    mine = api.get("/api/v1/schedule/summary", headers=pm).json()
    theirs = api.get("/api/v1/schedule/summary", headers=outsider).json()

    assert [s["project"]["code"] for s in mine] == ["HR-1"]
    assert mine[0]["actual_percent"] == 10.0
    assert mine[0]["planned_percent"] == round(15 / 31 * 100, 2)
    assert mine[0]["variance"] < 0
    assert theirs == []


def test_far_future_dates_are_refused(api: TestClient, project: Project, pm: dict[str, str]) -> None:
    """A task ending in 9999 would make every S-curve request compute ~400,000 weeks."""
    payload = {"name": "Forever", "planned_start": "2026-03-01", "planned_end": "9999-12-31", "weight": "10"}

    response = api.post(tasks_url(project), json=payload, headers=pm)

    assert response.status_code == 422
    assert "15 years" in response.json()["error"]["message"]
