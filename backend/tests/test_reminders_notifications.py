from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Database
from app.core.permissions import Role
from app.core.scheduler import build_scheduler, refresh_weather, run_report_reminders
from app.models import DailyReport, Notification, Project, Site, User, WeatherForecast
from app.services import notification_service, report_service
from app.services.notification_service import NewNotification
from tests.report_fixtures import TODAY, FakeWeather, Person

pytestmark = pytest.mark.usefixtures("site_today")


def _file_report(db: Session, project: Project, author: User) -> None:
    from app.core import clock

    db.add(
        DailyReport(
            project_id=project.id,
            author_id=author.id,
            report_date=TODAY,
            crew_count=10,
            work_done="Concrete pour on level 4 slab.",
            submitted_at=clock.utcnow(),
        )
    )
    db.commit()


def _notes(db: Session, user: User) -> list[Notification]:
    return list(db.scalars(select(Notification).where(Notification.user_id == user.id)).all())


# --- BR-07: missing-report reminder ------------------------------------------------------------


def test_reminder_fires_for_engineer_and_pm_when_no_report(
    db: Session, report_project: Project, engineer: Person, manager: Person, person: Callable[..., Person]
) -> None:
    qs = person(Role.QUANTITY_SURVEYOR)

    created = report_service.send_missing_report_reminders(db, TODAY)

    assert created == 2
    [for_engineer] = _notes(db, engineer.user)
    assert for_engineer.kind == "report_missing"
    assert for_engineer.link == f"/projects/{report_project.id}/reports/new"
    assert "Please submit it now" in for_engineer.body
    [for_pm] = _notes(db, manager.user)
    assert for_pm.link == f"/projects/{report_project.id}/reports"
    assert "site engineer has been reminded" in for_pm.body
    assert _notes(db, qs.user) == []


def test_pm_is_told_when_no_engineer_is_assigned(
    db: Session, report_project: Project, manager: Person
) -> None:
    report_service.send_missing_report_reminders(db, TODAY)

    [for_pm] = _notes(db, manager.user)
    assert "No site engineer is assigned" in for_pm.body


def test_reminder_is_sent_once_per_day(db: Session, report_project: Project, engineer: Person) -> None:
    assert report_service.send_missing_report_reminders(db, TODAY) == 1
    assert report_service.send_missing_report_reminders(db, TODAY) == 0
    assert report_service.send_missing_report_reminders(db, TODAY + timedelta(days=1)) == 1


def test_no_reminder_once_the_report_is_in(db: Session, report_project: Project, engineer: Person) -> None:
    _file_report(db, report_project, engineer.user)

    assert report_service.send_missing_report_reminders(db, TODAY) == 0


@pytest.mark.parametrize("change", ["project_planning", "project_on_hold", "site_closed", "not_started"])
def test_no_reminder_for_projects_that_are_not_running(
    db: Session, report_project: Project, report_site: Site, engineer: Person, change: str
) -> None:
    if change == "project_planning":
        report_project.status = "planning"
    elif change == "project_on_hold":
        report_project.status = "on_hold"
    elif change == "site_closed":
        report_site.is_active = False
    else:
        report_project.start_date = TODAY + timedelta(days=3)
    db.commit()

    assert report_service.send_missing_report_reminders(db, TODAY) == 0


def test_inactive_people_are_not_reminded(
    db: Session, report_project: Project, report_site: Site, make_user: Callable[..., User]
) -> None:
    make_user(Role.SITE_ENGINEER, sites=[report_site], active=False)

    assert report_service.send_missing_report_reminders(db, TODAY) == 0


def test_engineers_on_other_sites_are_not_reminded(
    db: Session, report_project: Project, person: Callable[..., Person], make_site: Callable[..., Site]
) -> None:
    other = person(Role.SITE_ENGINEER, sites=[make_site("KDY-02")])

    report_service.send_missing_report_reminders(db, TODAY)

    assert _notes(db, other.user) == []


def test_reminder_job_uses_its_own_session(
    db: Session, report_project: Project, engineer: Person, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []

    def factory() -> Session:
        calls.append(True)
        return db

    monkeypatch.setattr(db, "close", lambda: None)  # the test transaction stays open

    assert run_report_reminders(factory) == 1
    assert calls == [True]


def test_weather_job_refreshes_located_sites_and_survives_outages(
    db: Session, report_site: Site, make_site: Callable[..., Site], monkeypatch: pytest.MonkeyPatch
) -> None:
    make_site("NOLOC")  # no coordinates: skipped
    monkeypatch.setattr(db, "close", lambda: None)
    from tests.report_fixtures import sample_days

    assert refresh_weather(lambda: db, FakeWeather(days=sample_days())) == 1
    assert db.scalar(select(func.count(WeatherForecast.id))) == 5
    assert refresh_weather(lambda: db, FakeWeather(fail=True)) == 0


def test_scheduler_has_the_reminder_at_the_deadline(settings: Settings) -> None:
    database = Database(settings)
    scheduler = build_scheduler(settings, database, FakeWeather())

    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {"report_reminders", "weather_refresh"}
    assert str(jobs["report_reminders"].trigger) == "cron[hour='18', minute='0']"
    assert str(jobs["weather_refresh"].trigger) == "cron[hour='5', minute='30']"
    database.dispose()


def test_scheduled_jobs_never_raise(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    database = Database(settings)
    scheduler = build_scheduler(settings, database, FakeWeather())

    def boom(*args: object) -> int:
        raise RuntimeError("database down")

    monkeypatch.setattr("app.core.scheduler.run_report_reminders", boom)
    job = scheduler.get_job("report_reminders")

    job.func()  # logged, not raised
    database.dispose()


def test_app_starts_and_stops_the_scheduler_when_enabled(tmp_path: Any) -> None:
    from fastapi.testclient import TestClient as Client

    from app.main import create_app
    from tests.conftest import make_settings

    app = create_app(make_settings(scheduler_enabled=True, media_root=str(tmp_path)))
    with Client(app) as client:
        assert client.get("/api/v1/health").status_code == 200


# --- Notifications API ---------------------------------------------------------------------------


def test_users_see_and_mark_only_their_own_notifications(
    api: TestClient, db: Session, engineer: Person, manager: Person, report_project: Project
) -> None:
    notification_service.send(
        db,
        [
            NewNotification(engineer.user.id, "report_missing", "Mine", "For the engineer", link="/reports"),
            NewNotification(manager.user.id, "report_missing", "Theirs", "For the PM"),
        ],
    )
    db.commit()
    theirs = _notes(db, manager.user)[0]

    listing = api.get("/api/v1/notifications", headers=engineer.headers).json()
    assert [n["title"] for n in listing["items"]] == ["Mine"]
    assert listing["unread"] == 1

    assert api.post(f"/api/v1/notifications/{theirs.id}/read", headers=engineer.headers).status_code == 404
    db.refresh(theirs)
    assert theirs.read_at is None

    mine = listing["items"][0]["id"]
    read = api.post(f"/api/v1/notifications/{mine}/read", headers=engineer.headers)
    assert read.status_code == 200
    assert read.json()["read_at"] is not None
    assert api.get("/api/v1/notifications", headers=engineer.headers).json()["unread"] == 0


def test_mark_all_read_touches_only_the_caller(
    api: TestClient, db: Session, engineer: Person, manager: Person
) -> None:
    notification_service.send(
        db,
        [
            NewNotification(engineer.user.id, "k", "One", "b"),
            NewNotification(engineer.user.id, "k", "Two", "b"),
            NewNotification(manager.user.id, "k", "Three", "b"),
        ],
    )
    db.commit()

    assert api.post("/api/v1/notifications/read-all", headers=engineer.headers).status_code == 204

    assert api.get("/api/v1/notifications", headers=engineer.headers).json()["unread"] == 0
    assert api.get("/api/v1/notifications", headers=manager.headers).json()["unread"] == 1


@pytest.mark.parametrize(
    "link", ["https://evil.example/login", "//evil.example", "javascript:alert(1)", "x" * 201]
)
def test_only_in_app_links_are_stored(db: Session, engineer: Person, link: str) -> None:
    notification_service.send(db, [NewNotification(engineer.user.id, "k", "t", "b", link=link)])
    db.commit()

    assert _notes(db, engineer.user)[0].link is None


def test_long_text_is_trimmed(db: Session, engineer: Person) -> None:
    notification_service.send(db, [NewNotification(engineer.user.id, "k", "t" * 300, "b" * 900)])
    db.commit()

    note = _notes(db, engineer.user)[0]
    assert (len(note.title), len(note.body)) == (160, 500)


def test_notification_list_is_capped(api: TestClient, db: Session, engineer: Person) -> None:
    notification_service.send(db, [NewNotification(engineer.user.id, "k", f"n{i}", "b") for i in range(35)])
    db.commit()

    listing = api.get("/api/v1/notifications", headers=engineer.headers).json()

    assert len(listing["items"]) == 30
    assert listing["unread"] == 35
