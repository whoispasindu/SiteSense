"""Shared fixtures for the Phase 5 tests: a project with a priced BOQ, a team on its site, suppliers."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import clock
from app.core.permissions import Role
from app.models import BoqItem, BoqSection, BudgetLine, Project, Site, Supplier, User
from tests.conftest import bearer, login


@dataclass(frozen=True)
class Who:
    user: User
    headers: dict[str, str]


@dataclass(frozen=True)
class Boq:
    project: Project
    cement: BoqItem  # 1,000 bags at LKR 2,500; budgeted cost LKR 2,000 a bag
    steel: BoqItem  # 10 t at LKR 300,000; budgeted cost LKR 240,000 a tonne
    line: BudgetLine  # section budget: 80% of its BOQ value, LKR 4.4 million


@pytest.fixture
def mat_site(make_site: Callable[..., Site]) -> Site:
    return make_site("COL-07")


@pytest.fixture
def boq(db: Session, mat_site: Site) -> Boq:
    project = Project(
        code="HR-1", name="Havelock", site_id=mat_site.id, client_name="Client", project_type="residential",
        status="active", contract_value=Decimal("10000000.00"), start_date=date(2026, 1, 5),
        planned_end=date(2027, 12, 31),
    )  # fmt: skip
    db.add(project)
    db.flush()
    section = BoqSection(project_id=project.id, code="A", name="Materials", position=1)
    db.add(section)
    db.flush()
    cement = BoqItem(
        project_id=project.id, section_id=section.id, item_code="A.1", description="Cement, 50 kg bags",
        unit="bag", quantity=Decimal("1000"), rate=Decimal("2500"), amount=Decimal("2500000.00"), position=1,
    )  # fmt: skip
    steel = BoqItem(
        project_id=project.id, section_id=section.id, item_code="A.2", description="Reinforcement steel",
        unit="t", quantity=Decimal("10"), rate=Decimal("300000"), amount=Decimal("3000000.00"), position=2,
    )  # fmt: skip
    line = BudgetLine(project_id=project.id, section_id=section.id, budget_amount=Decimal("4400000.00"))
    db.add_all([cement, steel, line])
    db.commit()
    return Boq(project, cement, steel, line)


@pytest.fixture
def team(api: TestClient, make_user: Callable[..., User], mat_site: Site) -> Callable[..., Who]:
    def factory(role: Role, *, sites: list[Site] | None = None) -> Who:
        scoped = role not in (Role.PROCUREMENT_OFFICER, Role.ADMIN)
        user = make_user(role, sites=(sites if sites is not None else [mat_site]) if scoped else [])
        return Who(user, bearer(login(api, user.email)))

    return factory


@pytest.fixture
def se(team: Callable[..., Who]) -> Who:
    return team(Role.SITE_ENGINEER)


@pytest.fixture
def qs(team: Callable[..., Who]) -> Who:
    return team(Role.QUANTITY_SURVEYOR)


@pytest.fixture
def pm(team: Callable[..., Who]) -> Who:
    return team(Role.PROJECT_MANAGER)


@pytest.fixture
def buyer(team: Callable[..., Who]) -> Who:
    return team(Role.PROCUREMENT_OFFICER)


@pytest.fixture
def supplier(db: Session) -> Supplier:
    s = Supplier(name="Kelani Building Supplies", contact_name="Nimal", phone="+94 11 234 5678")
    db.add(s)
    db.commit()
    return s


def needed_by(days: int = 14) -> str:
    return (clock.site_today() + timedelta(days=days)).isoformat()


def request_body(boq: Boq, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "project_id": str(boq.project.id),
        "boq_item_id": str(boq.cement.id),
        "quantity": "100",
        # No price: site engineers do not see rates, so their requests start at the budgeted rate
        # (LKR 2,000 for cement) and the QS prices them at the QS check.
        "needed_by": needed_by(),
        "notes": "For the level 4 slab.",
    }
    body.update(overrides)
    return body


def raise_request(api: TestClient, boq: Boq, who: Who, **overrides: object) -> dict[str, object]:
    response = api.post("/api/v1/material-requests", json=request_body(boq, **overrides), headers=who.headers)
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


def decide(  # type: ignore[no-untyped-def]
    api: TestClient,
    request_id: object,
    who: Who,
    decision: str,
    comment: str | None = None,
    unit_price: str | None = None,
):
    body: dict[str, object] = {"decision": decision}
    if comment is not None:
        body["comment"] = comment
    if unit_price is not None:
        body["unit_price"] = unit_price
    return api.post(f"/api/v1/material-requests/{request_id}/decision", json=body, headers=who.headers)
