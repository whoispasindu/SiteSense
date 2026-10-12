"""Calls every protected endpoint as every role and checks the answer (Phase 1 'Done when').

When a new endpoint is added, add it to ENDPOINTS with the roles allowed to call it.
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import clock
from app.core.permissions import Role
from app.models import (
    BoqItem,
    BoqSection,
    BudgetLine,
    DailyReport,
    MaterialRequest,
    Project,
    ReportPhoto,
    Site,
    Supplier,
    Task,
    User,
)
from tests.conftest import bearer, login
from tests.report_fixtures import image_bytes

ALL_ROLES = frozenset(Role)
ADMIN_ONLY = frozenset({Role.ADMIN})
PROJECT_READERS = frozenset(
    {Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.SITE_ENGINEER, Role.PROCUREMENT_OFFICER}
)
PM_ONLY = frozenset({Role.PROJECT_MANAGER})
SCHEDULE_READERS = frozenset({Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.SITE_ENGINEER})
PROGRESS_EDITORS = frozenset({Role.PROJECT_MANAGER, Role.SITE_ENGINEER})
QS_ONLY = frozenset({Role.QUANTITY_SURVEYOR})
REPORT_READERS = frozenset({Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.SITE_ENGINEER})
SE_ONLY = frozenset({Role.SITE_ENGINEER})
MATERIAL_READERS = frozenset(
    {Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.SITE_ENGINEER, Role.PROCUREMENT_OFFICER}
)
REQUESTERS = frozenset({Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.SITE_ENGINEER})
COST_READERS = frozenset({Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR})
RISK_READERS = frozenset({Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR})
PROCUREMENT = frozenset({Role.PROCUREMENT_OFFICER})
VARIATION_MANAGERS = frozenset({Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR})
CLIENT_ONLY = frozenset({Role.CLIENT})
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
    photo: bool = False


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
    Endpoint("GET", "/api/v1/schedule/summary", SCHEDULE_READERS),
    Endpoint("GET", "/api/v1/projects/{project_id}/tasks", SCHEDULE_READERS),
    Endpoint("POST", "/api/v1/projects/{project_id}/tasks", PM_ONLY,
             {"name": "Matrix task", "planned_start": "2026-02-01", "planned_end": "2026-02-28",
              "weight": "10"}),
    Endpoint("PATCH", "/api/v1/tasks/{task_id}", PROGRESS_EDITORS, {"percent_complete": "10"}),
    Endpoint("DELETE", "/api/v1/tasks/{task_id}", PM_ONLY),
    Endpoint("GET", "/api/v1/projects/{project_id}/progress", SCHEDULE_READERS),
    Endpoint("GET", "/api/v1/projects/{project_id}/network", SCHEDULE_READERS),
    Endpoint("POST", "/api/v1/projects/{project_id}/dependencies", PM_ONLY,
             {"predecessor_id": "{task_id}", "successor_id": "{task_id}"}),
    Endpoint("DELETE", "/api/v1/dependencies/{dependency_id}", PM_ONLY),
    Endpoint("GET", "/api/v1/admin/holidays", ADMIN_ONLY),
    Endpoint("POST", "/api/v1/admin/holidays", ADMIN_ONLY,
             {"holiday_date": "2031-01-01", "name": "Matrix day"}),
    Endpoint("DELETE", "/api/v1/admin/holidays/{holiday_id}", ADMIN_ONLY),
    Endpoint("GET", "/api/v1/reports/today", REPORT_READERS),
    Endpoint("GET", "/api/v1/projects/{project_id}/reports", REPORT_READERS),
    Endpoint("POST", "/api/v1/projects/{project_id}/reports", SE_ONLY,
             {"report_date": "{today}", "crew_count": 3, "work_done": "Matrix work done today."}),
    Endpoint("GET", "/api/v1/reports/{report_id}", REPORT_READERS),
    Endpoint("PATCH", "/api/v1/reports/{report_id}", SE_ONLY, {"crew_count": 4}),
    Endpoint("POST", "/api/v1/reports/{report_id}/photos", SE_ONLY, photo=True),
    Endpoint("GET", "/api/v1/reports/{report_id}/issues", REPORT_READERS),
    Endpoint("POST", "/api/v1/reports/{report_id}/analyze", REPORT_READERS),
    Endpoint("POST", "/api/v1/reports/{report_id}/issues/confirm", REPORT_READERS, {"issues": []}),
    Endpoint("POST", "/api/v1/report-actions/{action_id}/close", REPORT_READERS, {"resolution": "done"}),
    Endpoint("PUT", "/api/v1/report-actions/{action_id}/stop-scope", REPORT_READERS, {"scope": "project"}),
    Endpoint("GET", "/api/v1/projects/{project_id}/report-actions", REPORT_READERS),
    Endpoint("GET", "/api/v1/photos/{photo_id}", REPORT_READERS),
    Endpoint("DELETE", "/api/v1/photos/{photo_id}", SE_ONLY),
    Endpoint("GET", "/api/v1/projects/{project_id}/weather", PROJECT_READERS),
    Endpoint("GET", "/api/v1/material-requests", MATERIAL_READERS),
    Endpoint("POST", "/api/v1/material-requests/check", REQUESTERS,
             {"project_id": "{project_id}", "boq_item_id": "{boq_item_id}", "quantity": "1",
              "unit_price": "10"}),
    Endpoint("POST", "/api/v1/material-requests", REQUESTERS,
             {"project_id": "{project_id}", "boq_item_id": "{boq_item_id}", "quantity": "1",
              "unit_price": "10", "needed_by": "{today}"}),
    Endpoint("GET", "/api/v1/material-requests/{request_id}", MATERIAL_READERS),
    Endpoint("GET", "/api/v1/material-requests/{request_id}/critical-path", MATERIAL_READERS),
    Endpoint("PUT", "/api/v1/material-requests/{request_id}/critical-path", PM_ONLY, {"critical": True}),
    Endpoint("GET", "/api/v1/suppliers/{supplier_id}/on-time", MATERIAL_READERS),
    Endpoint("GET", "/api/v1/projects/{project_id}/supplier-outlook", MATERIAL_READERS),
    Endpoint("PATCH", "/api/v1/material-requests/{request_id}", REQUESTERS, {"quantity": "2"}),
    Endpoint("POST", "/api/v1/material-requests/{request_id}/decision", REQUESTERS, {"decision": "approve"}),
    Endpoint("GET", "/api/v1/projects/{project_id}/boq-items", REQUESTERS),
    Endpoint("GET", "/api/v1/projects/{project_id}/budget", COST_READERS),
    Endpoint("GET", "/api/v1/suppliers", MATERIAL_READERS),
    Endpoint("POST", "/api/v1/suppliers", PROCUREMENT, {"name": "Matrix Supplies"}),
    Endpoint("PATCH", "/api/v1/suppliers/{supplier_id}", PROCUREMENT, {"contact_name": "Renamed"}),
    Endpoint("GET", "/api/v1/purchase-orders/ready", PROCUREMENT),
    Endpoint("GET", "/api/v1/purchase-orders", MATERIAL_READERS),
    Endpoint("POST", "/api/v1/purchase-orders", PROCUREMENT,
             {"supplier_id": "{supplier_id}", "expected_delivery": "{today}",
              "lines": [{"request_id": "{request_id}"}]}),
    Endpoint("GET", "/api/v1/purchase-orders/{order_id}", MATERIAL_READERS),
    Endpoint("POST", "/api/v1/purchase-orders/{order_id}/deliveries", PROCUREMENT,
             {"request_id": "{request_id}", "quantity": "1", "delivered_on": "{today}"}),
    Endpoint("GET", "/api/v1/cost/overview", COST_READERS),
    Endpoint("GET", "/api/v1/projects/{project_id}/claims", COST_READERS),
    Endpoint("POST", "/api/v1/projects/{project_id}/claims/check", QS_ONLY,
             {"sections": [{"section_id": "{section_id}", "certified_pct": "10"}]}),
    Endpoint("POST", "/api/v1/projects/{project_id}/claims", QS_ONLY,
             {"sections": [{"section_id": "{section_id}", "certified_pct": "10"}]}),
    Endpoint("GET", "/api/v1/claims/{claim_id}", COST_READERS),
    Endpoint("POST", "/api/v1/claims/{claim_id}/decision", PM_ONLY, {"decision": "approve"}),
    Endpoint("POST", "/api/v1/claims/{claim_id}/payment", QS_ONLY, {"paid_on": "{today}"}),
    Endpoint("GET", "/api/v1/projects/{project_id}/variations", VARIATION_MANAGERS),
    Endpoint("POST", "/api/v1/projects/{project_id}/variations", VARIATION_MANAGERS,
             {"title": "Matrix variation", "description": "Matrix change", "section_id": "{section_id}"}),
    Endpoint("GET", "/api/v1/variations/{variation_id}", VARIATION_MANAGERS),
    Endpoint("POST", "/api/v1/variations/{variation_id}/price", QS_ONLY,
             {"contract_change": "1.00", "budget_change": "1.00"}),
    Endpoint("POST", "/api/v1/variations/{variation_id}/revision", VARIATION_MANAGERS,
             {"title": "Matrix variation", "description": "Matrix change", "section_id": "{section_id}"}),
    Endpoint("POST", "/api/v1/variations/{variation_id}/decision", PM_ONLY, {"decision": "approve"}),
    Endpoint("POST", "/api/v1/variations/{variation_id}/withdraw", VARIATION_MANAGERS, {}),
    Endpoint("POST", "/api/v1/variations/{variation_id}/client-decision", CLIENT_ONLY,
             {"decision": "approve"}),
    Endpoint("GET", "/api/v1/client/variations", CLIENT_ONLY),
    Endpoint("GET", "/api/v1/client/variations/{variation_id}", CLIENT_ONLY),
    Endpoint("GET", "/api/v1/admin/variation-limits", ADMIN_ONLY),
    Endpoint("PUT", "/api/v1/admin/projects/{project_id}/variation-limit", ADMIN_ONLY,
             {"variation_limit": "5.00", "reason": "Matrix check"}),
    Endpoint("GET", "/api/v1/projects/{project_id}/risk", RISK_READERS),
    Endpoint("GET", "/api/v1/risk/projects", RISK_READERS),
    Endpoint("POST", "/api/v1/projects/{project_id}/risk/what-if", PM_ONLY, {"actions": []}),
    Endpoint("GET", "/api/v1/notifications", ALL_ROLES),
    Endpoint("POST", "/api/v1/notifications/{notification_id}/read", ALL_ROLES),
    Endpoint("POST", "/api/v1/notifications/read-all", ALL_ROLES),
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
    if endpoint.photo:
        return api.request(endpoint.method, path, files={"file": ("p.jpg", image_bytes())}, headers=headers)
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
    report = DailyReport(
        project_id=project.id,
        author_id=target.id,
        report_date=clock.site_today() - timedelta(days=1),
        crew_count=5,
        work_done="Matrix base report text.",
        submitted_at=clock.utcnow(),
    )
    db.add(report)
    db.flush()
    photo = ReportPhoto(
        report_id=report.id,
        uploaded_by=target.id,
        storage_key=f"{uuid.uuid4().hex}.jpg",
        content_type="image/jpeg",
        size_bytes=10,
        width=1,
        height=1,
        position=1,
        created_at=clock.utcnow(),
    )
    db.add(photo)
    item = BoqItem(
        project_id=project.id, section_id=section.id, item_code="A.1", description="Matrix item", unit="nr",
        quantity=Decimal("100"), rate=Decimal("10"), amount=Decimal("1000.00"), position=1,
    )  # fmt: skip
    db.add(item)
    db.flush()
    material = MaterialRequest(
        number="MR-9999", project_id=project.id, boq_item_id=item.id, requested_by=target.id,
        quantity=Decimal("1"), unit_price=Decimal("10"), needed_by=clock.site_today(), status="requested",
        approval_level="qs", submitted_at=clock.utcnow(),
    )  # fmt: skip
    supplier = Supplier(name="Matrix Base Supplier")
    db.add_all([material, supplier])
    task = Task(
        project_id=project.id,
        name="Matrix base task",
        planned_start=date(2026, 1, 5),
        planned_end=date(2026, 3, 31),
        weight=Decimal("50.00"),
        position=1,
    )
    db.add(task)
    db.commit()
    return {
        "task_id": str(task.id),
        "user_id": str(target.id),
        "site_id": str(site.id),
        "project_id": str(project.id),
        "budget_line_id": str(section.budget_line.id),
        "report_id": str(report.id),
        "photo_id": str(photo.id),
        "notification_id": str(uuid.uuid4()),
        "action_id": str(uuid.uuid4()),
        "today": clock.site_today().isoformat(),
        "boq_item_id": str(item.id),
        "request_id": str(material.id),
        "supplier_id": str(supplier.id),
        "order_id": str(uuid.uuid4()),
        "section_id": str(section.id),
        "claim_id": str(uuid.uuid4()),
        "variation_id": str(uuid.uuid4()),
        "dependency_id": str(uuid.uuid4()),
        "holiday_id": str(uuid.uuid4()),
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


# Sign-in, session and health routes: open to anyone or to every signed-in user, and tested in
# test_auth.py and test_health.py instead.
OUTSIDE_THE_MATRIX: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/health/ready"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/refresh"),
        ("POST", "/api/v1/auth/logout"),
        ("POST", "/api/v1/auth/change-password"),
    }
)


def _shape(method: str, path: str) -> tuple[str, str]:
    """Compare routes by shape: path parameter names do not matter."""
    return method.upper(), re.sub(r"\{[^}]+\}", "{}", path)


def test_every_api_route_is_in_the_matrix(app: FastAPI) -> None:
    """A new endpoint cannot ship without being listed here with the roles allowed to call it."""
    routes = {
        _shape(method, path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1")
        for method in operations
    }
    listed = {_shape(e.method, e.path) for e in ENDPOINTS}
    outside = {_shape(m, p) for m, p in OUTSIDE_THE_MATRIX}

    assert routes - listed - outside == set()
    assert listed - routes == set()  # nothing listed that no longer exists
