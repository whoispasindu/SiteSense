from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.database import get_db


def test_liveness_reports_ok_and_version(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.2.0-rc.1"}


class _BrokenSession:
    def execute(self, *_args: object, **_kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("password authentication failed for user x"))


def test_readiness_returns_503_without_leaking_database_errors(app: FastAPI, client: TestClient) -> None:
    def broken_db() -> Iterator[_BrokenSession]:
        yield _BrokenSession()

    app.dependency_overrides[get_db] = broken_db

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "checks": {"database": "unavailable"}}
    assert "password" not in response.text


@pytest.mark.integration
def test_readiness_against_real_database(api: TestClient) -> None:
    response = api.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_each_app_uses_its_own_database_settings() -> None:
    from app.main import create_app
    from tests.conftest import make_settings

    url = "postgresql+psycopg://someone:pw@db-for-this-app:5432/isolated"
    app = create_app(make_settings(database_url=url))

    assert app.state.database.engine.url.host == "db-for-this-app"
    assert app.state.database.engine.url.database == "isolated"
