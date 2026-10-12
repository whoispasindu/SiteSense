"""Phase 10: the supplier on-time model, supplier outlook, and BR-12 critical-path items."""

import copy
import math
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.supplier import model as supplier_model
from app.core.permissions import Role
from app.models import (
    AuditLog,
    Delivery,
    MaterialRequest,
    PurchaseOrder,
    PurchaseOrderLine,
    Site,
    Supplier,
    Task,
    User,
)
from app.services import supplier_service
from tests.materials_fixtures import Boq, Who

ON = date(2026, 7, 6)
NOW = ON  # orders are dated by their expected delivery only
_numbers = iter(range(1, 10_000))


def new_supplier(db: Session, name: str, *, active: bool = True) -> Supplier:
    s = Supplier(name=name, is_active=active)
    db.add(s)
    db.commit()
    return s


def order(
    db: Session, boq: Boq, who: User, supplier: Supplier, *, expected: date,
    arrived: list[tuple[date, str]], quantity: str = "10",
) -> PurchaseOrderLine:  # fmt: skip
    n = next(_numbers)
    request = MaterialRequest(
        number=f"MR-9{n:03d}", project_id=boq.project.id, boq_item_id=boq.cement.id, requested_by=who.id,
        quantity=Decimal(quantity), unit_price=Decimal("2000"), needed_by=expected, status="ordered",
        approval_level="qs", submitted_at=f"{ON.isoformat()}T04:00:00+00:00",
    )  # fmt: skip
    po = PurchaseOrder(
        number=f"PO-9{n:03d}", project_id=boq.project.id, supplier_id=supplier.id, issued_by=who.id,
        issued_at=f"{ON.isoformat()}T04:00:00+00:00", expected_delivery=expected, status="issued",
    )  # fmt: skip
    db.add_all([request, po])
    db.flush()
    line = PurchaseOrderLine(
        purchase_order_id=po.id, request_id=request.id, quantity=Decimal(quantity),
        unit_price=Decimal("2000"), amount=Decimal(quantity) * 2000, position=1,
    )  # fmt: skip
    db.add(line)
    db.flush()
    for day, qty in arrived:
        db.add(Delivery(line_id=line.id, quantity=Decimal(qty), delivered_on=day, received_by=who.id,
                        created_at=f"{ON.isoformat()}T04:00:00+00:00"))  # fmt: skip
    db.commit()
    return line


@pytest.fixture
def today(site_today: Callable[[date], None]) -> date:
    site_today(ON)
    return ON


# --- The model file -----------------------------------------------------------------------------------


def test_the_shipped_model_reproduces_its_training_code() -> None:
    model = supplier_model.current()

    assert model.version == supplier_model.CURRENT_VERSION
    assert len(model.golden) >= 20
    for row in model.golden:
        assert model.chance(row["inputs"]) == pytest.approx(row["p"], abs=1e-9)


def test_inputs_follow_the_smoothing_rules() -> None:
    model = supplier_model.current()

    fresh = model.inputs(supplier_on_time=0, supplier_count=0, company_on_time=0, company_count=0,
                         lead_time_days=14, wet_share=0.2)  # fmt: skip
    # No record anywhere: the default rate (80%), smoothed into itself.
    assert supplier_model.sigmoid(fresh["supplier_logit"]) == pytest.approx(0.8)
    # Two on time of two, with a company at 60% over 100 deliveries: pulled most of the way to the company.
    two = model.inputs(supplier_on_time=2, supplier_count=2, company_on_time=60, company_count=100,
                       lead_time_days=3, wet_share=0.2)  # fmt: skip
    company = (60 + 20 * 0.8) / 120
    assert supplier_model.sigmoid(two["supplier_logit"]) == pytest.approx((2 + 5 * company) / 7)
    assert two["short_lead"] == pytest.approx(4 / 7)
    assert two["log_deliveries"] == pytest.approx(math.log(3))


def _logistic_doc() -> dict[str, Any]:
    return {
        "format": "sitesense-supplier-v1", "version": "9.9.9", "kind": "logistic",
        "features": [*supplier_model.INPUTS, supplier_model.DERIVED], "intercept": 0.5,
        "coef": [1.0, 0.0, 0.0, -2.0, -1.0, 0.0],
        "constants": {"prior_strength": 5, "default_rate": 0.8, "company_prior_strength": 20,
                      "short_lead_days": 7, "low_data_deliveries": 5},
    }  # fmt: skip


def test_a_logistic_model_scores_too() -> None:
    m = supplier_model.parse(_logistic_doc())
    inputs = {
        "supplier_logit": 1.0,
        "log_deliveries": 2.0,
        "lead_time_days": 10.0,
        "wet_share": 0.3,
        "short_lead": 0.0,
    }

    assert m.chance(inputs) == pytest.approx(1 / (1 + math.exp(-(0.5 + 1.0 - 0.6))))
    with pytest.raises(supplier_model.SupplierModelError):
        m.chance({**inputs, "wet_share": math.nan})


@pytest.mark.parametrize(
    "change",
    [
        "format",
        "kind",
        "unknown input",
        "short coef",
        "text coef",
        "no intercept",
        "zero constant",
        "rate of one",
    ],
)
def test_malformed_supplier_models_are_refused(change: str) -> None:
    d = _logistic_doc()
    if change == "format":
        d["format"] = "pickle"
    elif change == "kind":
        d["kind"] = "neural"
    elif change == "unknown input":
        d["features"][0] = "supplier_postcode"
    elif change == "short coef":
        d["coef"] = d["coef"][:-1]
    elif change == "text coef":
        d["coef"][0] = "1.0"
    elif change == "no intercept":
        del d["intercept"]
    elif change == "zero constant":
        d["constants"]["prior_strength"] = 0
    elif change == "rate of one":
        d["constants"]["default_rate"] = 1
    with pytest.raises(supplier_model.SupplierModelError):
        supplier_model.parse(copy.deepcopy(d))


# --- Records: the same on-time rule as the risk model's late deliveries ----------------------------------


def test_a_suppliers_record_counts_lines_already_due(db: Session, boq: Boq, buyer: Who, today: date) -> None:
    kelani = new_supplier(db, "Kelani")
    week_ago = today - timedelta(days=7)
    order(
        db, boq, buyer.user, kelani, expected=week_ago, arrived=[(week_ago - timedelta(days=1), "10")]
    )  # early
    order(
        db, boq, buyer.user, kelani, expected=week_ago, arrived=[(week_ago, "6"), (week_ago, "4")]
    )  # on the day
    order(
        db, boq, buyer.user, kelani, expected=week_ago, arrived=[(week_ago, "6"), (today, "4")]
    )  # finished late
    order(db, boq, buyer.user, kelani, expected=week_ago, arrived=[])  # overdue
    order(db, boq, buyer.user, kelani, expected=today + timedelta(days=3), arrived=[])  # not due yet
    order(db, boq, buyer.user, kelani, expected=today, arrived=[(today, "10")])  # due today: not counted yet

    per_supplier, company = supplier_service.records(db, today)

    assert per_supplier[kelani.id] == supplier_service.Record(on_time=2, count=4)
    assert company == supplier_service.Record(on_time=2, count=4)


# --- Endpoints ------------------------------------------------------------------------------------------


def test_an_estimate_shows_its_range_and_the_deliveries_behind_it(
    api: TestClient, db: Session, boq: Boq, buyer: Who, today: date
) -> None:
    kelani, fresh = new_supplier(db, "Kelani"), new_supplier(db, "Fresh Hardware")
    due = today - timedelta(days=5)
    for k in range(12):
        order(db, boq, buyer.user, kelani, expected=due, arrived=[(due, "10")] if k < 9 else [])

    body = api.get(f"/api/v1/suppliers/{kelani.id}/on-time", headers=buyer.headers).json()
    new = api.get(f"/api/v1/suppliers/{fresh.id}/on-time", headers=buyer.headers).json()

    company = (9 + 20 * 0.8) / (12 + 20)
    assert body["chance"] == pytest.approx((9 + 5 * company) / (12 + 5), abs=0.001)
    assert body["chance_range"]["low"] < body["chance"] < body["chance_range"]["high"]
    assert (body["based_on"], body["low_data"], body["below_br12"]) == (12, False, False)
    assert body["model"] == "smoothed on-time rate"
    # No deliveries yet: the company's rate, marked as low data, with a wider range.
    assert (new["based_on"], new["low_data"]) == (0, True)

    def width(estimate: dict[str, Any]) -> float:
        return float(estimate["chance_range"]["high"] - estimate["chance_range"]["low"])

    assert width(new) > width(body)


def test_br12_marks_a_supplier_under_half(
    api: TestClient, db: Session, boq: Boq, buyer: Who, today: date
) -> None:
    slow = new_supplier(db, "Slow Steel")
    due = today - timedelta(days=5)
    for _ in range(20):
        order(db, boq, buyer.user, slow, expected=due, arrived=[])

    body = api.get(f"/api/v1/suppliers/{slow.id}/on-time", headers=buyer.headers).json()

    assert body["chance"] < 0.5
    assert body["below_br12"] is True


def critical_task(db: Session, boq: Boq) -> Task:
    """The project's only task, linked to the cement's BOQ section: critical by definition."""
    task = Task(project_id=boq.project.id, code="T-1", name="Slab", planned_start=date(2026, 1, 5),
                planned_end=date(2027, 12, 31), weight=Decimal("100"), position=1,
                boq_section_id=boq.cement.section_id)  # fmt: skip
    db.add(task)
    db.commit()
    return task


def approved_request(db: Session, boq: Boq, who: User) -> MaterialRequest:
    n = next(_numbers)
    request = MaterialRequest(
        number=f"MR-8{n:03d}", project_id=boq.project.id, boq_item_id=boq.cement.id, requested_by=who.id,
        quantity=Decimal("5"), unit_price=Decimal("2000"), needed_by=ON + timedelta(days=10),
        status="approved",
        approval_level="qs", submitted_at=f"{ON.isoformat()}T04:00:00+00:00",
    )  # fmt: skip
    db.add(request)
    db.commit()
    return request


def test_the_outlook_ranks_suppliers_and_names_critical_requests(
    api: TestClient, db: Session, boq: Boq, buyer: Who, se: Who, today: date
) -> None:
    good, poor = new_supplier(db, "Good Cement"), new_supplier(db, "Poor Cement")
    new_supplier(db, "Closed Supplies", active=False)
    due = today - timedelta(days=5)
    for _ in range(10):
        order(db, boq, buyer.user, good, expected=due, arrived=[(due, "10")])
        order(db, boq, buyer.user, poor, expected=due, arrived=[])
    critical_task(db, boq)
    request = approved_request(db, boq, se.user)

    body = api.get(
        f"/api/v1/projects/{boq.project.id}/supplier-outlook",
        params={"expected_delivery": (today + timedelta(days=10)).isoformat()},
        headers=buyer.headers,
    ).json()

    assert [s["supplier_name"] for s in body["suppliers"]] == [
        "Good Cement",
        "Poor Cement",
    ]  # active only, best first
    assert body["lead_time_days"] == 10
    assert body["threshold"] == 0.5
    assert body["critical_request_ids"] == [str(request.id)]


def test_the_pm_overrides_what_counts_as_critical(
    api: TestClient, db: Session, boq: Boq, pm: Who, se: Who, qs: Who, today: date
) -> None:
    request = approved_request(db, boq, se.user)
    url = f"/api/v1/material-requests/{request.id}/critical-path"

    automatic = api.get(url, headers=se.headers).json()
    assert (automatic["critical"], automatic["from_programme"], automatic["can_override"]) == (
        False,
        False,
        False,
    )
    assert "No critical or near-critical task" in automatic["reason"]

    assert api.put(url, json={"critical": True}, headers=se.headers).status_code == 403
    assert api.put(url, json={"critical": True}, headers=qs.headers).status_code == 403
    marked = api.put(url, json={"critical": True}, headers=pm.headers)

    assert marked.status_code == 200
    assert (marked.json()["critical"], marked.json()["override"]) == (True, True)
    assert marked.json()["reason"] == "Marked critical by the project manager."
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "material_request.critical_path_set"))
    assert entry is not None
    assert entry.details["after"] is True

    critical_task(db, boq)  # the programme now links it to a critical task...
    off = api.put(url, json={"critical": False}, headers=pm.headers).json()
    assert (off["critical"], off["from_programme"]) == (False, True)  # ...but the PM's "not critical" wins
    back = api.put(url, json={"critical": None}, headers=pm.headers).json()
    assert (back["critical"], back["override"]) == (True, None)
    assert back["reason"] == "Linked to T-1, a critical task."
    assert api.put(url, json={"critical": "yes"}, headers=pm.headers).status_code == 422


def test_near_critical_tasks_count_too(db: Session, boq: Boq, pm: Who, se: Who, today: date) -> None:
    """A task with float of 5 working days or less counts (here 3: 29 to 31 December); more does not."""
    # The frame is planned from today, so the forecast keeps its dates and the network ends 31 December.
    long = Task(project_id=boq.project.id, code="T-1", name="Frame", planned_start=ON,
                planned_end=date(2027, 12, 31), weight=Decimal("90"), position=1)  # fmt: skip
    short = Task(project_id=boq.project.id, code="T-2", name="Cement work", planned_start=date(2027, 12, 1),
                 planned_end=date(2027, 12, 28), weight=Decimal("10"), position=2,
                 boq_section_id=boq.cement.section_id)  # fmt: skip
    db.add_all([long, short])
    db.commit()
    request = approved_request(db, boq, se.user)

    near = supplier_service.critical_path(db, pm.user, request.id)

    assert near.critical is True
    assert "T-2, which has" in near.reason
    assert near.float_days == 5
    short.planned_end = date(2027, 12, 10)  # more float now
    db.commit()
    assert supplier_service.critical_path(db, pm.user, request.id).critical is False


def test_supplier_estimates_are_site_scoped(
    api: TestClient,
    db: Session,
    boq: Boq,
    team: Callable[..., Who],
    make_site: Callable[..., Site],
    today: date,
) -> None:
    outsider = team(Role.PROJECT_MANAGER, sites=[make_site("JAF-01")])
    kelani = new_supplier(db, "Kelani")
    request = approved_request(db, boq, outsider.user)

    outlook = f"/api/v1/projects/{boq.project.id}/supplier-outlook?expected_delivery={ON.isoformat()}"
    assert api.get(outlook, headers=outsider.headers).status_code == 404
    assert (
        api.get(f"/api/v1/material-requests/{request.id}/critical-path", headers=outsider.headers).status_code
        == 404
    )
    on_project = f"/api/v1/suppliers/{kelani.id}/on-time?project_id={boq.project.id}"
    assert api.get(on_project, headers=outsider.headers).status_code == 404
    assert api.get(f"/api/v1/suppliers/{uuid.uuid4()}/on-time", headers=outsider.headers).status_code == 404


@pytest.mark.parametrize(
    ("on_time", "count", "below", "low_data"),
    [
        (8, 20, True, False),  # (8 + 5 x 0.8) / 25 = 48%: under the BR-12 line
        (9, 20, False, False),  # 52%
        (3, 4, False, True),  # 4 deliveries: still low data
        (4, 5, False, False),  # 5: enough
    ],
)
def test_the_br12_line_and_the_low_data_mark(on_time: int, count: int, below: bool, low_data: bool) -> None:
    out = supplier_service.estimate(
        Supplier(id=uuid.uuid4(), name="Any"),
        supplier_service.Record(on_time, count),
        supplier_service.Record(0, 0),  # no company record: the 80% starting rate
        lead_time_days=14,
        wet_share=0.2,
    )

    assert (out.below_br12, out.low_data) == (below, low_data)
