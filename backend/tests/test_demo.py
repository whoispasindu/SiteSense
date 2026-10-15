"""Phase 13: demo mode. The nightly reset, logged emails and the seed in a production-style run."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, create_engine, func, select
from sqlalchemy.orm import Session

from app import cli
from app.core.database import Database
from app.core.scheduler import build_scheduler
from app.integrations import email as email_client
from app.integrations.storage import LocalStorage
from app.models import AuditLog, Holiday, Project, ReportPhoto, User
from app.services import demo_service
from tests.conftest import TEST_MIGRATION_URL, make_settings
from tests.report_fixtures import FakeWeather
from tests.test_cli import DEMO_PASSWORD, _TestDatabase

DEMO = {"demo_mode": True}


@pytest.fixture
def owner_connection(db_engine: Engine) -> Iterator[Connection]:
    """The reset runs as the schema owner (the app role may not delete audit rows): an owner
    connection whose transaction is rolled back at the end, like the usual test connection."""
    engine = create_engine(TEST_MIGRATION_URL)
    connection = engine.connect()
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def demo_db(
    monkeypatch: pytest.MonkeyPatch, owner_connection: Connection, tmp_path: Path
) -> Iterator[Session]:
    """The CLI on a rolled-back owner transaction, in demo mode, with a seeded demo."""
    db_connection = owner_connection
    settings = make_settings(media_root=str(tmp_path / "media"), weather_enabled=False, **DEMO)
    monkeypatch.setattr(cli, "Database", lambda _settings: _TestDatabase(db_connection))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setenv("SITESENSE_DEMO_PASSWORD", DEMO_PASSWORD)

    def reset_on_test_connection(s: object, storage: LocalStorage) -> demo_service.ResetResult:
        with Session(bind=db_connection, join_transaction_mode="create_savepoint") as db:
            return demo_service.reset(db, settings, storage)

    monkeypatch.setattr(demo_service, "reset_as_owner", reset_on_test_connection)
    assert cli.main(["seed-dev"]) == 0
    with Session(bind=db_connection, join_transaction_mode="create_savepoint") as session:
        yield session


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def test_the_reset_puts_the_demo_back(demo_db: Session, tmp_path: Path) -> None:
    """What a visitor did is gone; the seeded projects, accounts and photos are back."""
    seeded_projects = count(demo_db, Project)
    original_photos = set(demo_db.scalars(select(ReportPhoto.storage_key)))
    visitor = User(
        email="visitor@example.com", full_name="A Visitor", role="site_engineer", password_hash="x"
    )
    demo_db.add(visitor)
    demo_db.flush()
    site_id = demo_db.scalars(select(Project.site_id)).first()
    demo_db.add(
        Project(
            code="VISIT-1", name="Visitor's project", site_id=site_id, client_name="Visitor",
            project_type="residential", contract_value=Decimal("1000000"),
            start_date=date(2026, 10, 1), planned_end=date(2027, 10, 1),
        )
    )  # fmt: skip
    demo_db.add(
        Holiday(
            holiday_date=date(2027, 1, 2), name="Visitor's day off",
            created_by=visitor.id, created_at=visitor.created_at,
        )
    )  # fmt: skip
    demo_db.commit()
    migration_holidays = count(demo_db, Holiday) - 1

    assert cli.main(["reset-demo"]) == 0
    demo_db.expire_all()

    assert demo_db.scalar(select(User).where(User.email == "visitor@example.com")) is None
    assert demo_db.scalar(select(Project).where(Project.code == "VISIT-1")) is None
    assert count(demo_db, Project) == seeded_projects
    assert count(demo_db, Holiday) == migration_holidays
    assert all(u.is_demo for u in demo_db.scalars(select(User)))
    # The old photo files are deleted; the new seed stored its own.
    media = LocalStorage(tmp_path / "media")
    for key in original_photos:
        with pytest.raises(FileNotFoundError):
            media.read(key)
    assert count(demo_db, ReportPhoto) == len(original_photos)


def test_the_reset_also_clears_the_audit_log(demo_db: Session) -> None:
    """Run as the schema owner: the app's own role can never delete audit rows."""
    assert count(demo_db, AuditLog) > 0
    result = demo_service.reset(demo_db, make_settings(**DEMO), LocalStorage("unused"))
    assert result.rows > 0
    assert count(demo_db, AuditLog) == 0
    assert count(demo_db, User) == 0


def test_the_reset_refuses_outside_demo_mode(demo_db: Session) -> None:
    with pytest.raises(demo_service.DemoResetRefusedError, match="DEMO_MODE"):
        demo_service.reset(demo_db, make_settings(), LocalStorage("unused"))
    assert count(demo_db, Project) > 0


def test_the_reset_refuses_a_database_without_demo_accounts(db: Session) -> None:
    """Demo mode switched on by mistake over real data: nothing is deleted."""
    db.add(User(email="real@company.lk", full_name="Real Person", role="project_manager", password_hash="x"))
    db.commit()
    with pytest.raises(demo_service.DemoResetRefusedError, match="does not look like a demo"):
        demo_service.reset(db, make_settings(**DEMO), LocalStorage("unused"))
    assert db.scalar(select(User).where(User.email == "real@company.lk")) is not None


def test_reset_demo_command_refuses_outside_demo_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())
    assert cli.main(["reset-demo"]) == 1
    assert "DEMO_MODE" in capsys.readouterr().err
    with pytest.raises(demo_service.DemoResetRefusedError, match="DEMO_MODE"):
        demo_service.reset_as_owner(make_settings(), LocalStorage("unused"))


def test_the_nightly_reset_is_scheduled_only_in_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    normal = Database(make_settings())
    assert build_scheduler(make_settings(), normal, FakeWeather()).get_job("demo_reset") is None
    demo_settings = make_settings(**DEMO)
    scheduler = build_scheduler(demo_settings, normal, FakeWeather())
    job = scheduler.get_job("demo_reset")
    assert str(job.trigger) == "cron[hour='3', minute='0']"
    assert str(job.trigger.timezone) == "Asia/Colombo"

    ran: list[str] = []

    def fake_reset() -> int:
        ran.append("reset")
        return 0

    monkeypatch.setattr(cli, "reset_demo", fake_reset)
    job.func()
    assert ran == ["reset"]
    normal.dispose()


def test_demo_mode_never_sends_email_even_with_a_mail_server() -> None:
    with_smtp = {"smtp_host": "mail.test"}
    assert email_client.configured(make_settings(**with_smtp)) is True
    assert email_client.configured(make_settings(**with_smtp, **DEMO)) is False


def test_seed_dev_runs_in_production_only_in_demo_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    production = {
        "environment": "production",
        "app_base_url": "https://app.sitesense.example",
        "mfa_key": "a-real-production-mfa-key-value-0123456789abcdef",
        "mfa_enforced": True,
        "cors_origins": ["https://app.sitesense.example"],
        "database_url": "postgresql+psycopg://app:s3cure-pw@db:5432/sitesense",
        "jwt_secret": "a-real-production-secret-value-0123456789abcd",
    }
    monkeypatch.setenv("SITESENSE_DEMO_PASSWORD", "short")
    monkeypatch.setattr(cli, "get_settings", lambda: make_settings(**production, **DEMO))
    assert cli.main(["seed-dev"]) == 1
    # Past the production guard: stopped only by the password check.
    assert "Set SITESENSE_DEMO_PASSWORD" in capsys.readouterr().err


def test_the_demo_has_one_project_at_each_risk_level(
    monkeypatch: pytest.MonkeyPatch, owner_connection: Connection, tmp_path: Path
) -> None:
    """The guide's demo company: three projects at different risk levels (on the day this was set up;
    the scores move as the programme dates come closer, like a real project's)."""
    from datetime import UTC, datetime

    from app.core import clock
    from app.models import RiskScore

    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2026, 10, 16, 2, 0, tzinfo=UTC))
    monkeypatch.setattr(cli, "Database", lambda _settings: _TestDatabase(owner_connection))
    monkeypatch.setattr(cli, "get_settings", lambda: make_settings(media_root=str(tmp_path / "media")))
    monkeypatch.setenv("SITESENSE_DEMO_PASSWORD", DEMO_PASSWORD)
    assert cli.main(["seed-dev"]) == 0

    with Session(bind=owner_connection, join_transaction_mode="create_savepoint") as db:
        rows = db.execute(select(Project.code, RiskScore.level).join(RiskScore)).all()
    levels = {row.code: row.level for row in rows}
    assert levels == {"HR-2026-01": "high", "FVA-2026-03": "medium", "PRO-2026-02": "low"}
