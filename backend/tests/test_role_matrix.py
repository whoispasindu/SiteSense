"""Calls every protected endpoint as every role and checks the answer (Phase 1 'Done when').

When a new endpoint is added, add it to ENDPOINTS with the roles allowed to call it.
"""

from collections.abc import Callable
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.core.permissions import Role
from app.models import Site, User
from tests.conftest import bearer, login

ALL_ROLES = frozenset(Role)
ADMIN_ONLY = frozenset({Role.ADMIN})


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    allowed: frozenset[Role]
    body: dict[str, object] | None = None


ENDPOINTS = [
    Endpoint("GET", "/api/v1/me", ALL_ROLES),
    Endpoint("GET", "/api/v1/sites", ALL_ROLES),
    Endpoint("GET", "/api/v1/admin/users", ADMIN_ONLY),
    Endpoint("POST", "/api/v1/admin/users", ADMIN_ONLY,
             {"email": "matrix-new@site.lk", "full_name": "Matrix New", "role": "client"}),
    Endpoint("GET", "/api/v1/admin/users/{user_id}", ADMIN_ONLY),
    Endpoint("PATCH", "/api/v1/admin/users/{user_id}", ADMIN_ONLY, {"full_name": "Renamed Person"}),
    Endpoint("POST", "/api/v1/admin/users/{user_id}/sites", ADMIN_ONLY, {"site_ids": ["{site_id}"]}),
    Endpoint("POST", "/api/v1/admin/users/{user_id}/reset-password", ADMIN_ONLY),
    Endpoint("GET", "/api/v1/admin/sites", ADMIN_ONLY),
    Endpoint("POST", "/api/v1/admin/sites", ADMIN_ONLY,
             {"code": "MTX-1", "name": "Matrix", "location": "Galle"}),
    Endpoint("PATCH", "/api/v1/admin/sites/{site_id}", ADMIN_ONLY, {"name": "Renamed Site"}),
    Endpoint("GET", "/api/v1/admin/audit-logs", ADMIN_ONLY),
]  # fmt: skip


def _fill(value: object, ids: dict[str, str]) -> object:
    if isinstance(value, str):
        return value.format(**ids)
    if isinstance(value, list):
        return [_fill(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, ids) for k, v in value.items()}
    return value


def _call(api: TestClient, endpoint: Endpoint, ids: dict[str, str], headers: dict[str, str]):  # type: ignore[no-untyped-def]
    return api.request(
        endpoint.method, endpoint.path.format(**ids), json=_fill(endpoint.body, ids), headers=headers
    )


@pytest.fixture
def ids(make_user: Callable[..., User], make_site: Callable[..., Site]) -> dict[str, str]:
    site = make_site()
    target = make_user(Role.SITE_ENGINEER, sites=[site])
    return {"user_id": str(target.id), "site_id": str(site.id)}


@pytest.mark.parametrize("role", list(Role), ids=lambda r: r.value)
@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: f"{e.method} {e.path}")
def test_role_matrix(
    api: TestClient,
    make_user: Callable[..., User],
    ids: dict[str, str],
    endpoint: Endpoint,
    role: Role,
) -> None:
    caller = make_user(role)
    response = _call(api, endpoint, ids, bearer(login(api, caller.email)))

    if role in endpoint.allowed:
        assert response.status_code not in (401, 403), response.text
    else:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: f"{e.method} {e.path}")
def test_every_endpoint_requires_authentication(
    api: TestClient, ids: dict[str, str], endpoint: Endpoint
) -> None:
    response = _call(api, endpoint, ids, {})

    assert response.status_code == 401


def test_forbidden_request_changes_nothing(
    api: TestClient, make_user: Callable[..., User], ids: dict[str, str]
) -> None:
    """TC-01 pattern: a refused call must have no side effects."""
    engineer = make_user(Role.SITE_ENGINEER)
    admin = make_user(Role.ADMIN)
    headers = bearer(login(api, engineer.email))

    response = api.patch(f"/api/v1/admin/users/{ids['user_id']}", json={"is_active": False}, headers=headers)

    assert response.status_code == 403
    target = api.get(f"/api/v1/admin/users/{ids['user_id']}", headers=bearer(login(api, admin.email))).json()
    assert target["is_active"] is True
