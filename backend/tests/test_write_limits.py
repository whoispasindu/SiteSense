"""Phase 13: every write has a per-user budget, and the heavy endpoints a smaller one."""

import re
import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.api.deps import SIGN_IN_PATHS, WRITE_METHODS
from app.core.database import get_db
from app.core.permissions import Role
from app.main import create_app
from app.models import User
from tests.conftest import _session, bearer, login, make_settings

READ_ALL = "/api/v1/notifications/read-all"


@pytest.fixture
def tight_api(db_connection: Connection) -> Iterator[TestClient]:
    """The API with budgets small enough to reach in a test."""
    app: FastAPI = create_app(
        make_settings(write_rate_per_minute=3, heavy_rate_per_minute=2, login_rate_per_minute=50)
    )

    def override_get_db() -> Iterator[Session]:
        session = _session(db_connection)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def test_writes_are_limited_per_user_not_per_office(
    tight_api: TestClient, make_user: Callable[..., User]
) -> None:
    """Two people behind one office IP: the first runs out, the second still has a full budget."""
    first = bearer(login(tight_api, make_user().email))
    second = bearer(login(tight_api, make_user().email))

    statuses = [tight_api.post(READ_ALL, headers=first).status_code for _ in range(4)]
    assert statuses == [204, 204, 204, 429]
    assert tight_api.post(READ_ALL, headers=second).status_code == 204


def test_the_limited_response_says_when_to_try_again(
    tight_api: TestClient, make_user: Callable[..., User]
) -> None:
    headers = bearer(login(tight_api, make_user().email))
    for _ in range(3):
        tight_api.post(READ_ALL, headers=headers)

    limited = tight_api.post(READ_ALL, headers=headers)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(limited.headers["Retry-After"]) <= 61


def test_reads_do_not_use_the_write_budget(tight_api: TestClient, make_user: Callable[..., User]) -> None:
    headers = bearer(login(tight_api, make_user().email))
    for _ in range(5):
        assert tight_api.get("/api/v1/notifications", headers=headers).status_code == 200
    assert tight_api.post(READ_ALL, headers=headers).status_code == 204


def test_a_forged_token_counts_against_the_ip_not_a_user(
    tight_api: TestClient, make_user: Callable[..., User]
) -> None:
    """An invalid token cannot spend (or hide behind) a real user's budget."""
    forged = {"Authorization": "Bearer not-a-real-token"}
    statuses = [tight_api.post(READ_ALL, headers=forged).status_code for _ in range(4)]
    assert statuses == [401, 401, 401, 429]

    # A new forged token each time does not open a fresh budget: they all count against the IP.
    other = {"Authorization": "Bearer another-made-up-token"}
    assert tight_api.post(READ_ALL, headers=other).status_code == 429

    real = bearer(login(tight_api, make_user().email))
    assert tight_api.post(READ_ALL, headers=real).status_code == 204


def test_the_weekly_pdf_has_its_own_smaller_budget(
    tight_api: TestClient, make_user: Callable[..., User]
) -> None:
    headers = bearer(login(tight_api, make_user(Role.PROJECT_MANAGER).email))
    statuses = [tight_api.get("/api/v1/reports/weekly.pdf", headers=headers).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


def test_signing_in_is_not_blocked_by_the_write_budget(
    tight_api: TestClient, make_user: Callable[..., User]
) -> None:
    """Sign-in has its own per-IP budget; a burst of other writes from the office must not lock it."""
    forged = {"Authorization": "Bearer not-a-real-token"}
    for _ in range(4):
        tight_api.post(READ_ALL, headers=forged)
    for _ in range(4):
        login(tight_api, make_user().email)


def test_every_write_route_has_the_write_budget(tight_api: TestClient) -> None:
    """Each write in the API schema, called twice with a write budget of one, is refused the second
    time: a route mounted outside the API router would escape the budget, and this catches it."""
    app: FastAPI = tight_api.app  # type: ignore[assignment]
    app.state.settings.write_rate_per_minute = 1
    limiter = app.state.rate_limiter
    writes = [
        (method.upper(), re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.upper() in WRITE_METHODS
    ]
    assert len(writes) > 50
    escaped = []
    for method, path in writes:
        limiter.reset()
        tight_api.request(method, path)
        if tight_api.request(method, path).status_code != 429 and path not in SIGN_IN_PATHS:
            escaped.append(f"{method} {path}")
    assert escaped == []
