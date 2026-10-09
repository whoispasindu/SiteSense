"""Calls every protected endpoint as every role and checks the answer (Phase 1 'Done when').

When a new endpoint is added, add it to ENDPOINTS with the roles allowed to call it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models import BoqSection, BudgetLine, Project, Site, User
from tests.conftest import bearer, login

ALL_ROLES = frozenset(Role)
ADMIN_ONLY = frozenset({Role.ADMIN})
PROJECT_READERS = frozenset(
    {Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.SITE_ENGINEER, Role.PROCUREMENT_OFFICER}
)
PM_ONLY = frozenset({Role.PROJECT_MANAGER})
QS_ONLY = frozenset({Role.QUANTITY_SURVEYOR})
BOQ_CSV = (
    b"Section Code,Section Name,Item Code,Description,Unit,Quantity,Rate\nA,Prelims,A.1,Setup,item,1,100\n"
)


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    allowed: frozenset[Role]
    body: dict[str, object] | None = None
    upload: bool = False


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
    Endpoint("GET", "/api/v1/projects", PROJECT_READERS),
    Endpoint("POST", "/api/v1/projects", PM_ONLY,
             {"code": "MTX-P", "name": "Matrix Project", "site_id": "{site_id}", "client_name": "Client Co",
              "project_type": "commercial", "contract_value": "1000.00", "start_date": "2026-01-01",
              "planned_end": "2026-12-31"}),
    Endpoint("GET", "/api/v1/projects/{project_id}", PROJECT_READERS),
    Endpoint("PATCH", "/api/v1/projects/{project_id}", PM_ONLY, {"name": "Renamed Project"}),
    Endpoint("GET", "/api/v1/projects/{project_id}/boq", PROJECT_READERS),
    Endpoint("POST", "/api/v1/projects/{project_id}/boq/import", QS_ONLY, upload=True),
    Endpoint("PATCH", "/api/v1/projects/{project_id}/budget-lines/{budget_line_id}", QS_ONLY,
             {"budget_amount": "50.00"}),
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
    path = endpoint.path.format(**ids)
    if endpoint.upload:
        return api.request(endpoint.method, path, files={"file": ("boq.csv", BOQ_CSV)}, headers=headers)
    return api.request(endpoint.method, path, json=_fill(endpoint.body, ids), headers=headers)


@pytest.fixture
def ids(make_user: Callable[..., User], make_site: Callable[..., Site], db: Session) -> dict[str, str]:
    site = make_site()
    target = make_user(Role.SITE_ENGINEER, sites=[site])
    project = Project(
        code="MTX-BASE",
        name="Matrix Base",
        site_id=site.id,
        client_name="Client Co",
        project_type="residential",
        status="active",
        contract_value=Decimal("1000.00"),
        start_date=date(2026, 1, 1),
        planned_end=date(2026, 12, 31),
    )
    db.add(project)
    db.flush()
    section = BoqSection(project_id=project.id, code="A", name="Prelims", position=1)
    section.budget_line = BudgetLine(project_id=project.id, budget_amount=Decimal("100.00"))
    db.add(section)
    db.commit()
    return {
        "user_id": str(target.id),
        "site_id": str(site.id),
        "project_id": str(project.id),
        "budget_line_id": str(section.budget_line.id),
    }


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
