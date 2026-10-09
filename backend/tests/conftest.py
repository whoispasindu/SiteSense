import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not depend on the developer's shell: drop every SITESENSE_* variable except the
    test database URL, and skip any local .env file."""
    for key in list(os.environ):
        if key.startswith("SITESENSE_") and key != "SITESENSE_TEST_DATABASE_URL":
            monkeypatch.delenv(key)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": SecretStr(
            os.environ.get(
                "SITESENSE_TEST_DATABASE_URL",
                "postgresql+psycopg://sitesense_app:test@127.0.0.1:5432/sitesense_test",
            )
        ),
        "cors_origins": ["http://localhost:5173"],
        "allowed_hosts": ["testserver", "localhost"],
        "max_request_body_bytes": 2048,
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
