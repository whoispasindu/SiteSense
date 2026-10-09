from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.permissions import Role
from app.models import AuditLog, DailyReport, Notification, ProgressSnapshot, Project, Site, Task
from tests.conftest import make_settings
from tests.report_fixtures import TODAY, FakeWeather, Person, report_body

pytestmark = pytest.mark.usefixtures("site_today")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Room for 5,000-character report text in the body.
    return make_settings(media_root=str(tmp_path / "media"), max_request_body_bytes=64 * 1024)


def reports_url(project: Project) -> str:
    return f"/api/v1/projects/{project.id}/reports"


def submit(api: TestClient, project: Project, who: Person, **overrides: object) -> dict[str, object]:
    response = api.post(reports_url(project), json=report_body(**overrides), headers=who.headers)
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


# --- Submitting ---------------------------------------------------------------------------


def test_engineer_submits_a_report_that_the_pm_can_read(
    api: TestClient, report_project: Project, engineer: Person, manager: Person
) -> None:
    created = submit(api, report_project, engineer)

    assert created["report_date"] == TODAY.isoformat()
    assert created["author"]["full_name"] == engineer.user.full_name  # type: ignore[index]
    assert created["crew_count"] == 42
    assert created["rain_mm"] == "6.2"
    assert created["editable"] is True
    assert created["photo_limit"] == 12

    read = api.get(f"/api/v1/reports/{created['id']}", headers=manager.headers)
    assert read.status_code == 200
    assert read.json()["work_done"].startswith("Fixed reinforcement")
    assert read.json()["editable"] is False  # the PM reads, only the author edits

    listing = api.get(reports_url(report_project), headers=manager.headers).json()
    assert listing["total"] == 1
    assert listing["items"][0]["has_problems"] is True
    assert listing["items"][0]["photo_count"] == 0


def test_second_report_for_the_same_day_is_blocked_with_a_link(
    api: TestClient, report_project: Project, engineer: Person, person: Callable[..., Person]
) -> None:
    """TC-03: refused with a clear message; the engineer can open and edit the first one."""
    first = submit(api, report_project, engineer)
    other_engineer = person(Role.SITE_ENGINEER)

    response = api.post(reports_url(report_project), json=report_body(), headers=other_engineer.headers)

    assert response.status_code == 409
    error = response.json()["error"]
    assert "already exists" in error["message"]
    assert error["details"][0]["report_id"] == first["id"]


@pytest.mark.parametrize(
    ("field", "value"),
    ids=lambda v: str(v)[:12],
    argvalues=[
        ("work_done", None),
        ("work_done", "too short"),
        ("work_done", "x" * 5001),
        ("crew_count", None),
        ("crew_count", -1),
        ("crew_count", 5001),
        ("report_date", None),
        ("report_date", "09/10/2026"),
        ("rain_mm", "-1"),
        ("temp_max_c", "99"),
        ("weather_source", "satellite"),
        ("weather_summary", "x" * 61),
    ],
)
def test_required_and_bounded_fields_are_validated(
    api: TestClient, report_project: Project, engineer: Person, field: str, value: object
) -> None:
    response = api.post(
        reports_url(report_project), json=report_body(**{field: value}), headers=engineer.headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_fields_are_rejected(api: TestClient, report_project: Project, engineer: Person) -> None:
    response = api.post(
        reports_url(report_project), json=report_body(author_id="someone-else"), headers=engineer.headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("day", "message"),
    [
        (TODAY + timedelta(days=1), "future"),
        (TODAY - timedelta(days=8), "late"),
    ],
)
def test_report_dates_are_today_or_recent(
    api: TestClient, report_project: Project, engineer: Person, day: date, message: str
) -> None:
    response = api.post(
        reports_url(report_project), json=report_body(report_date=day.isoformat()), headers=engineer.headers
    )

    assert response.status_code == 422
    assert message in response.json()["error"]["message"]


def test_late_report_within_a_week_is_accepted(
    api: TestClient, report_project: Project, engineer: Person
) -> None:
    week_ago = (TODAY - timedelta(days=7)).isoformat()
    created = submit(api, report_project, engineer, report_date=week_ago)

    assert created["report_date"] == week_ago


def test_reports_cannot_predate_the_project(
    api: TestClient, report_project: Project, engineer: Person, db: Session
) -> None:
    report_project.start_date = TODAY
    db.commit()

    response = api.post(
        reports_url(report_project),
        json=report_body(report_date=(TODAY - timedelta(days=1)).isoformat()),
        headers=engineer.headers,
    )

    assert response.status_code == 422
    assert "before the project starts" in response.json()["error"]["message"]


@pytest.mark.parametrize("status", ["planning", "completed", "cancelled"])
def test_reports_only_for_running_projects(
    api: TestClient, report_project: Project, engineer: Person, db: Session, status: str
) -> None:
    report_project.status = status
    db.commit()

    response = api.post(reports_url(report_project), json=report_body(), headers=engineer.headers)

    assert response.status_code == 422


def test_on_hold_projects_still_take_reports(
    api: TestClient, report_project: Project, engineer: Person, db: Session
) -> None:
    report_project.status = "on_hold"
    db.commit()

    submit(api, report_project, engineer)


def test_blank_problems_are_stored_as_none(
    api: TestClient, report_project: Project, engineer: Person
) -> None:
    created = submit(api, report_project, engineer, problems="   ")

    assert created["problems"] is None


# --- Task progress through the report -------------------------------------------------------


def test_report_progress_updates_the_programme(
    api: TestClient, report_project: Project, report_task: Task, engineer: Person, db: Session
) -> None:
    created = submit(
        api, report_project, engineer, progress=[{"task_id": str(report_task.id), "percent_complete": "35.5"}]
    )

    assert created["progress"] == [
        {"task_id": str(report_task.id), "task_name": "Frame level 4", "percent_before": "20.00",
         "percent_after": "35.50"}
    ]  # fmt: skip
    db.refresh(report_task)
    assert report_task.percent_complete == Decimal("35.50")
    assert report_task.progress_updated_at is not None
    snapshot = db.scalar(select(ProgressSnapshot).where(ProgressSnapshot.project_id == report_project.id))
    assert snapshot is not None
    assert snapshot.snapshot_date == TODAY
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "report.created"))
    assert entry is not None
    assert entry.details["tasks_updated"] == ["T-010"]


def test_progress_for_another_projects_task_is_refused(
    api: TestClient, report_project: Project, engineer: Person, db: Session, report_site: Site
) -> None:
    other = Project(
        code="OTHER", name="Other", site_id=report_site.id, client_name="C", project_type="commercial",
        status="active", contract_value=Decimal("1.00"), start_date=date(2026, 1, 1),
        planned_end=date(2026, 12, 31),
    )  # fmt: skip
    db.add(other)
    db.flush()
    foreign = Task(
        project_id=other.id, name="Foreign", planned_start=date(2026, 1, 1), planned_end=date(2026, 2, 1),
        weight=Decimal("10"), position=1,
    )  # fmt: skip
    db.add(foreign)
    db.commit()

    response = api.post(
        reports_url(report_project),
        json=report_body(progress=[{"task_id": str(foreign.id), "percent_complete": "50"}]),
        headers=engineer.headers,
    )

    assert response.status_code == 422
    db.refresh(foreign)
    assert foreign.percent_complete == 0
    assert db.scalar(select(DailyReport)) is None  # nothing saved


def test_progress_needs_the_progress_permission_too(
    api: TestClient,
    report_project: Project,
    report_task: Task,
    engineer: Person,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defence in depth: a role allowed to file reports but not to move progress cannot do it here."""
    from app.core import permissions

    reduced = permissions.ROLE_PERMISSIONS[Role.SITE_ENGINEER] - {permissions.Permission.SCHEDULE_PROGRESS}
    monkeypatch.setitem(permissions.ROLE_PERMISSIONS, Role.SITE_ENGINEER, reduced)

    response = api.post(
        reports_url(report_project),
        json=report_body(progress=[{"task_id": str(report_task.id), "percent_complete": "90"}]),
        headers=engineer.headers,
    )

    assert response.status_code == 403
    db.refresh(report_task)
    assert report_task.percent_complete == Decimal("20.00")
    without_progress = api.post(reports_url(report_project), json=report_body(), headers=engineer.headers)
    assert without_progress.status_code == 201


def test_progress_entries_must_be_unique_and_in_range(
    api: TestClient, report_project: Project, report_task: Task, engineer: Person
) -> None:
    entry = {"task_id": str(report_task.id), "percent_complete": "10"}
    duplicate = api.post(
        reports_url(report_project), json=report_body(progress=[entry, entry]), headers=engineer.headers
    )
    too_high = api.post(
        reports_url(report_project),
        json=report_body(progress=[{"task_id": str(report_task.id), "percent_complete": "100.5"}]),
        headers=engineer.headers,
    )

    assert duplicate.status_code == 422
    assert too_high.status_code == 422


# --- Weather pre-fill -----------------------------------------------------------------------


def test_omitted_weather_is_filled_from_the_cached_forecast(
    api: TestClient, report_project: Project, engineer: Person, fake_weather: FakeWeather
) -> None:
    api.get(f"/api/v1/projects/{report_project.id}/weather", headers=engineer.headers)  # warms the cache

    created = submit(
        api, report_project, engineer, weather_summary=None, temp_max_c=None, temp_min_c=None, rain_mm=None
    )

    assert created["weather_summary"] == "Partly cloudy"
    assert created["temp_max_c"] == "31.0"
    assert created["rain_mm"] == "0.0"
    assert created["weather_source"] == "forecast"


def test_without_a_forecast_weather_stays_empty(
    api: TestClient, report_project: Project, engineer: Person
) -> None:
    created = submit(
        api, report_project, engineer, weather_summary=None, temp_max_c=None, temp_min_c=None, rain_mm=None
    )

    assert created["weather_summary"] is None
    assert created["weather_source"] == "manual"


# --- Corrections ----------------------------------------------------------------------------


def test_author_can_correct_the_report_on_the_same_day(
    api: TestClient, report_project: Project, engineer: Person, db: Session
) -> None:
    created = submit(api, report_project, engineer)

    response = api.patch(
        f"/api/v1/reports/{created['id']}", json={"crew_count": 50, "problems": ""}, headers=engineer.headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["crew_count"] == 50
    assert response.json()["problems"] is None
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "report.updated"))
    assert entry is not None
    assert entry.details["fields"] == ["crew_count", "problems"]


def test_required_fields_cannot_be_cleared(
    api: TestClient, report_project: Project, engineer: Person
) -> None:
    created = submit(api, report_project, engineer)

    response = api.patch(
        f"/api/v1/reports/{created['id']}", json={"work_done": None}, headers=engineer.headers
    )

    assert response.status_code == 422


def test_reports_are_locked_after_the_day_of_submission(
    api: TestClient,
    report_project: Project,
    engineer: Person,
    db: Session,
    site_today: Callable[[date], None],
) -> None:
    created = submit(api, report_project, engineer)
    report = db.get(DailyReport, created["id"])
    assert report is not None
    report.submitted_at = report.submitted_at - timedelta(days=1)
    db.commit()

    response = api.patch(f"/api/v1/reports/{created['id']}", json={"crew_count": 1}, headers=engineer.headers)

    assert response.status_code == 422
    assert "day they were submitted" in response.json()["error"]["message"]


def test_only_the_author_can_correct(
    api: TestClient, report_project: Project, engineer: Person, person: Callable[..., Person]
) -> None:
    created = submit(api, report_project, engineer)
    colleague = person(Role.SITE_ENGINEER)

    response = api.patch(
        f"/api/v1/reports/{created['id']}", json={"crew_count": 1}, headers=colleague.headers
    )

    assert response.status_code == 403


# --- Access (BR-03) -------------------------------------------------------------------------


def test_reports_on_other_sites_are_invisible(
    api: TestClient,
    report_project: Project,
    engineer: Person,
    person: Callable[..., Person],
    make_site: Callable[..., Site],
) -> None:
    created = submit(api, report_project, engineer)
    elsewhere = make_site("KDY-02")
    outsider = person(Role.PROJECT_MANAGER, sites=[elsewhere])
    outside_engineer = person(Role.SITE_ENGINEER, sites=[elsewhere])

    assert api.get(f"/api/v1/reports/{created['id']}", headers=outsider.headers).status_code == 404
    assert api.get(reports_url(report_project), headers=outsider.headers).status_code == 404
    body = report_body(report_date=(TODAY - timedelta(days=1)).isoformat())
    response = api.post(reports_url(report_project), json=body, headers=outside_engineer.headers)
    assert response.status_code == 404


def test_quantity_surveyor_reads_but_cannot_submit(
    api: TestClient, report_project: Project, engineer: Person, person: Callable[..., Person]
) -> None:
    submit(api, report_project, engineer)
    qs = person(Role.QUANTITY_SURVEYOR)

    assert api.get(reports_url(report_project), headers=qs.headers).status_code == 200
    body = report_body(report_date=(TODAY - timedelta(days=1)).isoformat())
    response = api.post(reports_url(report_project), json=body, headers=qs.headers)
    assert response.status_code == 403


def test_missing_report_is_404(api: TestClient, engineer: Person) -> None:
    response = api.get("/api/v1/reports/00000000-0000-4000-8000-000000000000", headers=engineer.headers)

    assert response.status_code == 404


def test_listing_is_newest_first_and_paginated(
    api: TestClient, report_project: Project, engineer: Person
) -> None:
    for days_ago in range(3):
        submit(api, report_project, engineer, report_date=(TODAY - timedelta(days=days_ago)).isoformat())

    page = api.get(
        reports_url(report_project), params={"limit": 2, "offset": 1}, headers=engineer.headers
    ).json()

    assert page["total"] == 3
    expected = [(TODAY - timedelta(days=n)).isoformat() for n in (1, 2)]
    assert [item["report_date"] for item in page["items"]] == expected
    assert (
        api.get(reports_url(report_project), params={"limit": 101}, headers=engineer.headers).status_code
        == 422
    )


# --- Today's status and notifications ------------------------------------------------------------


def test_today_status_shows_which_projects_have_reported(
    api: TestClient, report_project: Project, engineer: Person, manager: Person
) -> None:
    before = api.get("/api/v1/reports/today", headers=manager.headers).json()
    assert before["date"] == TODAY.isoformat()
    assert [p["report_id"] for p in before["projects"]] == [None]

    created = submit(api, report_project, engineer)
    after = api.get("/api/v1/reports/today", headers=manager.headers).json()

    assert after["projects"][0]["report_id"] == created["id"]
    assert after["projects"][0]["author_name"] == engineer.user.full_name
    assert after["deadline"].endswith("18:00:00+05:30")


def test_pm_is_notified_when_a_report_is_filed(
    api: TestClient, report_project: Project, engineer: Person, manager: Person, db: Session
) -> None:
    created = submit(api, report_project, engineer)

    notes = api.get("/api/v1/notifications", headers=manager.headers).json()

    assert notes["unread"] == 1
    assert notes["items"][0]["kind"] == "report_submitted"
    assert notes["items"][0]["link"] == f"/reports/{created['id']}"
    assert "noted problems" in notes["items"][0]["body"]
    # The engineer who filed it is not notified about their own report.
    assert db.scalar(select(Notification).where(Notification.user_id == engineer.user.id)) is None
