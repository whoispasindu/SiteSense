from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from app import cli
from app.core import clock
from app.core.security import verify_password
from app.models import (
    AuditLog,
    DailyReport,
    HandoverPublication,
    MaterialRequest,
    ProgressSnapshot,
    Project,
    PurchaseOrder,
    ReportPhoto,
    RiskScore,
    Site,
    Supplier,
    Task,
    User,
)
from app.services import supplier_service
from tests.conftest import make_settings
from tests.report_fixtures import FakeWeather

DEMO_PASSWORD = "Demo-Password-For-Tests-1"


class _TestDatabase:
    """Stands in for app.core.database.Database, bound to the rolled-back test transaction."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def session_factory(self) -> Session:
        return Session(bind=self.connection, join_transaction_mode="create_savepoint")

    def dispose(self) -> None:
        pass


@pytest.fixture
def cli_db(monkeypatch: pytest.MonkeyPatch, db_connection: Connection, tmp_path: Path) -> Iterator[Session]:
    monkeypatch.setattr(cli, "Database", lambda _settings: _TestDatabase(db_connection))
    # The demo seed stores photos (Phase 12): into a per-test folder, never the source tree.
    monkeypatch.setattr(cli, "get_settings", lambda: make_settings(media_root=str(tmp_path / "media")))
    with Session(bind=db_connection, join_transaction_mode="create_savepoint") as session:
        yield session


def test_create_admin_prints_a_one_time_password(cli_db: Session, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["create-admin", "--email", "Owner@Company.LK", "--name", "Company Owner"]) == 0

    output = capsys.readouterr().out
    temporary = output.strip().splitlines()[-1].rsplit(": ", 1)[1]
    admin = cli_db.scalar(select(User).where(User.email == "owner@company.lk"))
    assert admin is not None
    assert admin.role == "admin"
    assert admin.must_change_password is True
    assert verify_password(temporary, admin.password_hash)
    assert cli_db.scalar(select(AuditLog).where(AuditLog.target_id == str(admin.id))) is not None


def test_create_admin_refuses_duplicates(cli_db: Session) -> None:
    assert cli.main(["create-admin", "--email", "dup@company.lk", "--name", "First One"]) == 0
    assert cli.main(["create-admin", "--email", "DUP@company.lk", "--name", "Second One"]) == 1


def test_seed_dev_creates_sites_and_one_user_per_role(
    cli_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SITESENSE_DEMO_PASSWORD", DEMO_PASSWORD)

    assert cli.main(["seed-dev"]) == 0
    assert cli.main(["seed-dev"]) == 0  # idempotent

    users = cli_db.scalars(select(User).where(User.email.like("%@sitesense.example"))).all()
    assert sorted(u.role for u in users) == sorted(
        ["admin", "project_manager", "quantity_surveyor", "site_engineer", "procurement_officer", "client"]
    )
    assert all(verify_password(DEMO_PASSWORD, u.password_hash) for u in users)
    assert {s.code for s in cli_db.scalars(select(Site)).all()} >= {"COL-07", "KDY-02", "GAL-11"}
    havelock = cli_db.scalar(select(Project).where(Project.code == "HR-2026-01"))
    assert havelock is not None
    tasks = cli_db.scalars(select(Task).where(Task.project_id == havelock.id)).all()
    assert len(tasks) == 11
    assert sum(t.weight for t in tasks) == Decimal("100.00")
    assert (
        cli_db.scalar(select(ProgressSnapshot).where(ProgressSnapshot.project_id == havelock.id)) is not None
    )
    reports = cli_db.scalars(select(DailyReport).where(DailyReport.project_id == havelock.id)).all()
    assert len(reports) >= 12  # the week in DEMO_REPORTS plus two earlier weeks with gaps
    assert len({r.report_date for r in reports}) == len(reports)  # one report a day, even after a re-run
    # Today's report is left for the demo engineer to file.
    assert clock.site_today() not in {r.report_date for r in reports}
    # Phase 6: every open demo project has its inputs and a risk score from the shipped model.
    projects = cli_db.scalars(select(Project).where(Project.code.in_(cli.DEMO_CREWS))).all()
    assert {p.code: p.planned_crew for p in projects} == cli.DEMO_CREWS
    scores = cli_db.scalars(select(RiskScore)).all()
    assert {s.project_id for s in scores} == {p.id for p in projects}
    assert all(s.score_date == clock.site_today() for s in scores)
    overdue = cli_db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.project_id == havelock.id, PurchaseOrder.expected_delivery < clock.site_today()
        )
    ).all()
    assert len(overdue) == 2
    statuses = sorted(
        r.status
        for r in cli_db.scalars(select(MaterialRequest).where(MaterialRequest.project_id == havelock.id))
    )
    assert statuses == ["approved", "change_requested", "delivered", "ordered", "pm_approval", "requested"]
    assert cli_db.scalar(select(func.count(Supplier.id))) == 5
    # BR-12 (Phase 10): a finished job gives every supplier an on-time record, and is never risk-scored.
    finished = cli_db.scalar(select(Project).where(Project.code == cli.DEMO_HISTORY_PROJECT[0]))
    assert finished is not None
    assert finished.status == "completed"
    assert finished.id not in {s.project_id for s in scores}
    records, _ = supplier_service.records(cli_db, clock.site_today())
    by_name = {s.name: s.id for s in cli_db.scalars(select(Supplier))}
    for name, _item, orders, on_time in cli.DEMO_SUPPLIER_HISTORY:
        history = records[by_name[name]]
        assert history.count >= orders  # plus any Havelock orders already due
        assert history.on_time >= on_time
    # Phase 12: the client portal has milestones, a published handover date with history, and photos,
    # all but the newest shared.
    milestones = [t.milestone_name for t in tasks if t.client_milestone]
    assert sorted(milestones) == sorted(cli.DEMO_MILESTONES.values())  # type: ignore[type-var]
    published = cli_db.scalars(
        select(HandoverPublication).where(HandoverPublication.project_id == havelock.id)
    ).all()
    assert [p.kind for p in published] == ["published", "published"]
    photos = cli_db.scalars(
        select(ReportPhoto).join(DailyReport).where(DailyReport.project_id == havelock.id)
    ).all()
    assert len(photos) == len(cli.DEMO_PHOTOS)
    assert sum(p.shared_with_client for p in photos) == len(cli.DEMO_PHOTOS) - 1


def test_send_reminders_command(cli_db: Session, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["send-reminders"]) == 0

    assert "reminder notifications" in capsys.readouterr().out


def test_refresh_weather_command(
    cli_db: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "OpenMeteoClient", lambda _timeout: FakeWeather(fail=True))

    assert cli.main(["refresh-weather"]) == 0

    assert "Refreshed the forecast for 0 sites" in capsys.readouterr().out


def test_seed_dev_needs_a_valid_password(cli_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITESENSE_DEMO_PASSWORD", "short")
    assert cli.main(["seed-dev"]) == 1


def test_seed_dev_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    production = make_settings(
        environment="production",
        app_base_url="https://app.sitesense.example",
        mfa_key="a-real-production-mfa-key-value-0123456789abcdef",
        mfa_enforced=True,
        cors_origins=["https://app.sitesense.example"],
        database_url="postgresql+psycopg://app:s3cure-pw@db:5432/sitesense",
        jwt_secret="a-real-production-secret-value-0123456789abcd",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: production)
    assert cli.main(["seed-dev"]) == 1


def test_score_risk_command(cli_db: Session, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["score-risk"]) == 0

    assert "Scored" in capsys.readouterr().out


def test_strip_photo_metadata_command(
    cli_db: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SITESENSE_DEMO_PASSWORD", DEMO_PASSWORD)
    assert cli.main(["seed-dev"]) == 0
    capsys.readouterr()

    assert cli.main(["strip-photo-metadata", "--dry-run"]) == 0
    assert capsys.readouterr().out.strip() == (
        f"Checked {len(cli.DEMO_PHOTOS)} photos: would clean 0 files; 0 files missing."
    )
    assert cli.main(["strip-photo-metadata"]) == 0
    assert "cleaned 0 files" in capsys.readouterr().out
