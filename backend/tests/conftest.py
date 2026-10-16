import os
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.core.database import get_db
from app.core.permissions import Role
from app.core.security import hash_password
from app.main import create_app
from app.models import Site, User

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Defaults match the docker compose database, so `pytest` works after `docker compose up -d db`.
TEST_DATABASE_URL = os.environ.get(
    "SITESENSE_TEST_DATABASE_URL",
    "postgresql+psycopg://sitesense_app:change-me-app@127.0.0.1:5432/sitesense_test",
)
TEST_MIGRATION_URL = os.environ.get(
    "SITESENSE_TEST_MIGRATION_DATABASE_URL",
    "postgresql+psycopg://sitesense_owner:change-me-owner@127.0.0.1:5432/sitesense_test",
)

PASSWORD = "Correct-Horse-Battery-9"

pytest_plugins = ["tests.report_fixtures", "tests.materials_fixtures", "tests.dashboard_fixtures"]


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not depend on the developer's shell: drop every SITESENSE_* variable except the
    test database URLs, and skip any local .env file."""
    for key in list(os.environ):
        if key.startswith("SITESENSE_") and not key.startswith("SITESENSE_TEST_"):
            monkeypatch.delenv(key)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": SecretStr(TEST_DATABASE_URL),
        "cors_origins": ["http://localhost:5173"],
        "allowed_hosts": ["testserver", "localhost"],
        "max_request_body_bytes": 2048,
        "jwt_secret": SecretStr("test-jwt-secret-that-is-long-enough-0123456789"),
        # No network calls and no background threads in tests.
        "weather_enabled": False,
        "scheduler_enabled": False,
        # Two-step sign-in is tested on its own (test_mfa.py turns enforcement on).
        "mfa_enforced": False,
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Photo files go to a per-test folder, never into the source tree.
    return make_settings(media_root=str(tmp_path / "media"))


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


# --- Database -------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    engine = create_engine(TEST_DATABASE_URL, connect_args={"connect_timeout": 3})
    try:
        engine.connect().close()
    except OperationalError:
        if os.environ.get("CI"):
            pytest.fail("CI must provide a PostgreSQL test database (SITESENSE_TEST_DATABASE_URL)")
        pytest.skip("PostgreSQL test database not reachable; run `docker compose up -d db`")
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_MIGRATION_URL)
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_connection(db_engine: Engine) -> Iterator[Connection]:
    """One outer transaction per test, rolled back at the end: tests never see each other's data."""
    connection = db_engine.connect()
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()


def _session(connection: Connection) -> Session:
    # Service-level commits become savepoint releases inside the outer test transaction.
    return Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest.fixture
def db(db_connection: Connection) -> Iterator[Session]:
    session = _session(db_connection)
    yield session
    session.close()


@pytest.fixture
def api(app: FastAPI, db_connection: Connection) -> Iterator[TestClient]:
    """HTTPS test client (the refresh cookie is Secure) whose requests use the test transaction."""

    def override_get_db() -> Iterator[Session]:
        session = _session(db_connection)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


# --- Factories and helpers ----------------------------------------------------------------


@pytest.fixture
def make_site(db: Session) -> Callable[..., Site]:
    def factory(code: str | None = None, *, active: bool = True) -> Site:
        code = code or f"S-{uuid.uuid4().hex[:6].upper()}"
        site = Site(code=code, name=f"Site {code}", location="Colombo", is_active=active)
        db.add(site)
        db.commit()
        return site

    return factory


_PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    def factory(
        role: Role = Role.SITE_ENGINEER,
        *,
        email: str | None = None,
        sites: list[Site] | None = None,
        active: bool = True,
        must_change_password: bool = False,
    ) -> User:
        user = User(
            email=email or f"{role.value}-{uuid.uuid4().hex[:8]}@sitesense.example",
            full_name=f"Test {role.value.replace('_', ' ').title()}",
            role=role.value,
            password_hash=_PASSWORD_HASH,
            is_active=active,
            must_change_password=must_change_password,
            sites=sites or [],
        )
        db.add(user)
        db.commit()
        return user

    return factory


def login(api: TestClient, email: str, password: str = PASSWORD) -> str:
    response = api.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> Callable[[timedelta], None]:
    """Freeze time; call the returned function to move it forward."""
    state = {"now": datetime.now(UTC)}
    monkeypatch.setattr(clock, "utcnow", lambda: state["now"])

    def advance(delta: timedelta) -> None:
        state["now"] = state["now"] + delta

    return advance
