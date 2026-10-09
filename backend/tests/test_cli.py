from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app import cli
from app.core.security import verify_password
from app.models import AuditLog, Site, User
from tests.conftest import make_settings

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
def cli_db(monkeypatch: pytest.MonkeyPatch, db_connection: Connection) -> Iterator[Session]:
    monkeypatch.setattr(cli, "Database", lambda _settings: _TestDatabase(db_connection))
    monkeypatch.setattr(cli, "get_settings", make_settings)
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


def test_seed_dev_needs_a_valid_password(cli_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITESENSE_DEMO_PASSWORD", "short")
    assert cli.main(["seed-dev"]) == 1


def test_seed_dev_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    production = make_settings(
        environment="production",
        cors_origins=["https://app.sitesense.example"],
        database_url="postgresql+psycopg://app:s3cure-pw@db:5432/sitesense",
        jwt_secret="a-real-production-secret-value-0123456789abcd",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: production)
    assert cli.main(["seed-dev"]) == 1
