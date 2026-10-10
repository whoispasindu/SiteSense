from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.core.permissions import Role
from app.models import AuditLog, MaterialRequest, Notification, Site, Supplier, User
from tests.conftest import make_settings
from tests.materials_fixtures import Boq, Who, decide, needed_by, raise_request, request_body

URL = "/api/v1/material-requests"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Room for long notes in a request body (the default test limit is 2 KB).
    return make_settings(media_root=str(tmp_path / "media"), max_request_body_bytes=64 * 1024)


def notes_for(db: Session, user: User) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at)
        )
    )


def order(api: TestClient, who: Who, supplier: Supplier, *request_ids: object, **line: object):  # type: ignore[no-untyped-def]
    return api.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": str(supplier.id),
            "expected_delivery": needed_by(7),
            "lines": [{"request_id": str(rid), **line} for rid in request_ids],
        },
        headers=who.headers,
    )


def deliver(api: TestClient, who: Who, po_id: object, request_id: object, quantity: str):  # type: ignore[no-untyped-def]
    return api.post(
        f"/api/v1/purchase-orders/{po_id}/deliveries",
        json={
            "request_id": str(request_id),
            "quantity": quantity,
            "delivered_on": clock.site_today().isoformat(),
        },
        headers=who.headers,
    )


# --- Raising requests ------------------------------------------------------------------------------


def test_engineer_raises_a_request_routed_to_the_qs(
    api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who, db: Session
) -> None:
    created = raise_request(api, boq, se)

    assert created["number"] == "MR-0001"
    assert created["status"] == "requested"
    assert created["approval_level"] == "qs"
    assert created["amount"] == "200000.00"
    assert created["rules"]["blocked"] is False  # type: ignore[index]
    assert [r["rule"] for r in created["rules"]["results"]] == ["BR-02", "BR-01"]  # type: ignore[index]
    assert created["rules"]["budget_rate"] == "2000.00"  # type: ignore[index]
    assert created["history"][0]["action"] == "submit"  # type: ignore[index]
    assert created["actions"] == ["cancel"]  # the requester can only cancel
    [note] = notes_for(db, qs.user)
    assert note.kind == "request_pending"
    assert note.link == f"/materials/{created['id']}"
    assert notes_for(db, pm.user) == []
    assert db.scalar(select(AuditLog).where(AuditLog.action == "material_request.created")) is not None


def test_request_six_percent_over_budget_goes_to_the_pm(
    api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who
) -> None:
    """TC-02 (BR-01)."""
    created = raise_request(api, boq, se, unit_price="2120")

    assert created["approval_level"] == "pm"
    assert "Needs project manager approval" in created["rules"]["results"][1]["message"]  # type: ignore[index]

    approved = decide(api, created["id"], qs, "approve")
    assert approved.json()["status"] == "pm_approval"  # the QS check passes it on, it does not approve it
    assert decide(api, created["id"], qs, "approve").status_code == 403  # nor can the QS finish it
    assert decide(api, created["id"], pm, "approve").json()["status"] == "approved"


@pytest.mark.parametrize("quantity", ["0", "-5", "0.0000"])
def test_zero_or_negative_quantity_is_a_validation_error(
    api: TestClient, boq: Boq, se: Who, db: Session, quantity: str
) -> None:
    """TC-04: validation error, nothing saved."""
    response = api.post(URL, json=request_body(boq, quantity=quantity), headers=se.headers)

    assert response.status_code == 422
    assert db.scalar(select(func.count(MaterialRequest.id))) == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unit_price", "0"),
        ("unit_price", "-1"),
        ("quantity", "1.0001"),
        ("notes", "x" * 2001),
        ("needed_by", "soon"),
    ],
    ids=["price-zero", "price-negative", "quantity-precision", "notes-too-long", "date-text"],
)
def test_other_fields_are_validated(api: TestClient, boq: Boq, se: Who, field: str, value: str) -> None:
    assert api.post(URL, json=request_body(boq, **{field: value}), headers=se.headers).status_code == 422


def test_quantity_above_the_boq_allowance_is_blocked(api: TestClient, boq: Boq, se: Who, db: Session) -> None:
    """BR-02: everything requested for an item stays within the BOQ quantity plus 3%."""
    raise_request(api, boq, se, quantity="1000")

    response = api.post(URL, json=request_body(boq, quantity="31"), headers=se.headers)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "rule_blocked"
    assert error["details"] == [{"rule": "BR-02"}]
    assert "approved variation" in error["message"]
    assert db.scalar(select(func.count(MaterialRequest.id))) == 1
    # 30 more is exactly the 3% tolerance.
    assert raise_request(api, boq, se, quantity="30")["status"] == "requested"


def test_rejected_and_cancelled_requests_free_their_quantity(
    api: TestClient, boq: Boq, se: Who, qs: Who
) -> None:
    first = raise_request(api, boq, se, quantity="1000")
    decide(api, first["id"], qs, "reject", "Order from the central store instead.")

    assert raise_request(api, boq, se, quantity="1000")["status"] == "requested"


def test_check_endpoint_previews_the_rules_without_saving(
    api: TestClient, boq: Boq, se: Who, db: Session
) -> None:
    response = api.post(
        f"{URL}/check",
        json={
            "project_id": str(boq.project.id),
            "boq_item_id": str(boq.cement.id),
            "quantity": "2000",
            "unit_price": "2500",
        },
        headers=se.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["blocked"] is True
    assert body["approval_level"] == "pm"
    assert body["amount"] == "5000000.00"
    assert db.scalar(select(func.count(MaterialRequest.id))) == 0


@pytest.mark.parametrize(("days", "message"), [(-1, "past"), (800, "two years")])
def test_needed_by_must_be_sensible(api: TestClient, boq: Boq, se: Who, days: int, message: str) -> None:
    response = api.post(URL, json=request_body(boq, needed_by=needed_by(days)), headers=se.headers)

    assert response.status_code == 422
    assert message in response.json()["error"]["message"]


def test_item_must_belong_to_the_project(api: TestClient, boq: Boq, se: Who) -> None:
    response = api.post(
        URL, json=request_body(boq, boq_item_id="00000000-0000-4000-8000-000000000000"), headers=se.headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize("status", ["planning", "completed", "cancelled"])
def test_only_running_projects_take_requests(
    api: TestClient, boq: Boq, se: Who, db: Session, status: str
) -> None:
    boq.project.status = status
    db.commit()

    assert api.post(URL, json=request_body(boq), headers=se.headers).status_code == 422


def test_unknown_fields_are_rejected(api: TestClient, boq: Boq, se: Who) -> None:
    response = api.post(URL, json=request_body(boq, status="approved"), headers=se.headers)

    assert response.status_code == 422


# --- Decisions ------------------------------------------------------------------------------------------


def test_site_engineer_cannot_approve_and_nothing_changes(
    api: TestClient, boq: Boq, se: Who, team: Callable[..., Who], db: Session
) -> None:
    """TC-01."""
    created = raise_request(api, boq, team(Role.SITE_ENGINEER))

    response = decide(api, created["id"], se, "approve")

    assert response.status_code == 403
    assert "waiting for the quantity surveyor" in response.json()["error"]["message"]
    assert db.get(MaterialRequest, created["id"]).status == "requested"  # type: ignore[union-attr]


def test_requester_cannot_approve_their_own_request(
    api: TestClient, boq: Boq, qs: Who, team: Callable[..., Who], db: Session
) -> None:
    """TC-05 (BR-04): a QS who raised a request cannot approve it; another QS can."""
    created = raise_request(api, boq, qs)

    response = decide(api, created["id"], qs, "approve")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "own_request"
    assert (
        response.json()["error"]["message"] == "You cannot approve or reject a request you raised yourself."
    )
    assert db.get(MaterialRequest, created["id"]).status == "requested"  # type: ignore[union-attr]
    assert decide(api, created["id"], team(Role.QUANTITY_SURVEYOR), "approve").json()["status"] == "approved"


def test_pm_who_raised_a_request_cannot_approve_it_either(
    api: TestClient, boq: Boq, pm: Who, qs: Who, team: Callable[..., Who]
) -> None:
    created = raise_request(api, boq, pm, unit_price="2500")  # 25% over: needs a PM
    decide(api, created["id"], qs, "approve")

    assert decide(api, created["id"], pm, "approve").status_code == 403
    assert decide(api, created["id"], team(Role.PROJECT_MANAGER), "approve").json()["status"] == "approved"


def test_invalid_transitions_are_refused(api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who) -> None:
    created = raise_request(api, boq, se)
    assert decide(api, created["id"], pm, "approve").status_code == 403  # the PM cannot skip the QS check
    decide(api, created["id"], qs, "approve")

    again = decide(api, created["id"], qs, "approve")
    late_cancel = decide(api, created["id"], se, "cancel")

    assert again.status_code == 409
    assert "No decision is pending" in again.json()["error"]["message"]
    assert late_cancel.status_code == 409
    assert late_cancel.json()["error"]["code"] == "invalid_transition"


def test_reject_and_change_need_a_comment(api: TestClient, boq: Boq, se: Who, qs: Who, db: Session) -> None:
    created = raise_request(api, boq, se)

    assert decide(api, created["id"], qs, "reject").status_code == 422
    assert decide(api, created["id"], qs, "request_change", "   ").status_code == 422
    rejected = decide(api, created["id"], qs, "reject", "Duplicate of MR-0007.")
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["history"][-1]["comment"] == "Duplicate of MR-0007."
    [note] = notes_for(db, se.user)
    assert note.kind == "request_rejected"
    assert "Duplicate of MR-0007." in note.body


def test_change_requested_then_resubmitted(api: TestClient, boq: Boq, se: Who, qs: Who, db: Session) -> None:
    created = raise_request(api, boq, se)
    changed = decide(api, created["id"], qs, "request_change", "Split into two deliveries.").json()
    assert changed["status"] == "change_requested"
    assert changed["actions"] == []  # the QS waits for the requester now

    mine = api.get(f"{URL}/{created['id']}", headers=se.headers).json()
    assert mine["actions"] == ["edit", "cancel"]
    response = api.patch(
        f"{URL}/{created['id']}", json={"quantity": "50", "comment": "Halved."}, headers=se.headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "requested"
    assert body["quantity"] == "50.000"
    assert [h["action"] for h in body["history"]] == ["submit", "request_change", "resubmit"]
    assert body["history"][-1]["comment"] == "Halved."
    assert len([n for n in notes_for(db, qs.user) if n.kind == "request_pending"]) == 2


def test_only_the_requester_edits_and_only_when_asked(
    api: TestClient, boq: Boq, se: Who, qs: Who, team: Callable[..., Who]
) -> None:
    created = raise_request(api, boq, se)
    assert api.patch(f"{URL}/{created['id']}", json={"quantity": "5"}, headers=se.headers).status_code == 409

    decide(api, created["id"], qs, "request_change", "Too much.")
    other = team(Role.SITE_ENGINEER)
    assert (
        api.patch(f"{URL}/{created['id']}", json={"quantity": "5"}, headers=other.headers).status_code == 403
    )
    assert api.patch(f"{URL}/{created['id']}", json={"quantity": None}, headers=se.headers).status_code == 422
    assert (
        api.patch(f"{URL}/{created['id']}", json={"quantity": "5000"}, headers=se.headers).status_code == 422
    )


def test_requester_can_cancel_but_nobody_else(api: TestClient, boq: Boq, se: Who, qs: Who) -> None:
    created = raise_request(api, boq, se)

    assert decide(api, created["id"], qs, "cancel").status_code == 403
    assert decide(api, created["id"], se, "cancel").json()["status"] == "cancelled"


def test_qs_approval_rechecks_routing_with_current_figures(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier, team: Callable[..., Who]
) -> None:
    """Approval uses today's commitments: a request that fitted at submission can need the PM later."""
    late = raise_request(api, boq, se, quantity="20", unit_price="2000")  # fits the budget today
    # Meanwhile steel is bought far over budget, so the line will end more than 5% over.
    big = raise_request(
        api, boq, team(Role.SITE_ENGINEER), boq_item_id=str(boq.steel.id), quantity="10", unit_price="460000"
    )
    decide(api, big["id"], qs, "approve")
    decide(api, big["id"], team(Role.PROJECT_MANAGER), "approve")

    response = decide(api, late["id"], qs, "approve")

    assert response.json()["status"] == "pm_approval"
    assert response.json()["approval_level"] == "pm"


# --- Ordering and delivery ----------------------------------------------------------------------------


def test_full_flow_from_site_to_delivery_updates_the_budget(
    api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who, buyer: Who, supplier: Supplier, db: Session
) -> None:
    """Phase 5 "Done when": correct routing, and the budget figures update by themselves."""
    budget_url = f"/api/v1/projects/{boq.project.id}/budget"
    created = raise_request(api, boq, se, quantity="100", unit_price="2000")
    decide(api, created["id"], qs, "approve")

    after_approval = api.get(budget_url, headers=pm.headers).json()["totals"]
    assert (after_approval["approved"], after_approval["committed"], after_approval["spent"]) == (
        "200000.00", "0.00", "0.00",
    )  # fmt: skip
    assert [n.kind for n in notes_for(db, buyer.user)] == ["request_ready_to_order"]
    ready = api.get("/api/v1/purchase-orders/ready", headers=buyer.headers).json()
    assert [r["number"] for r in ready] == ["MR-0001"]

    po = order(api, buyer, supplier, created["id"], unit_price="1950")
    assert po.status_code == 201, po.text
    po_body = po.json()
    assert po_body["number"] == "PO-0001"
    assert po_body["total"] == "195000.00"
    after_order = api.get(budget_url, headers=pm.headers).json()["totals"]
    assert (after_order["approved"], after_order["committed"]) == ("0.00", "195000.00")

    part = deliver(api, buyer, po_body["id"], created["id"], "40")
    assert part.status_code == 201, part.text
    assert part.json()["status"] == "part_delivered"
    mid = api.get(budget_url, headers=pm.headers).json()["totals"]
    assert (mid["committed"], mid["spent"]) == ("117000.00", "78000.00")

    done = deliver(api, buyer, po_body["id"], created["id"], "60").json()
    assert done["status"] == "delivered"
    final = api.get(budget_url, headers=pm.headers).json()
    assert (final["totals"]["committed"], final["totals"]["spent"]) == ("0.00", "195000.00")
    assert final["totals"]["remaining"] == "4205000.00"
    assert final["lines"][0]["variance"] == "4205000.00"

    request = api.get(f"{URL}/{created['id']}", headers=se.headers).json()
    assert request["status"] == "delivered"
    assert request["order"]["delivered_quantity"] == "100.000"
    assert [h["action"] for h in request["history"]] == ["submit", "approve", "order", "deliver"]
    assert [n.kind for n in notes_for(db, se.user)] == [
        "request_approved", "request_ordered", "request_part_delivered", "request_delivered",
    ]  # fmt: skip
    actions = {e.action for e in db.scalars(select(AuditLog))}
    assert {"material_request.decided", "purchase_order.issued", "delivery.recorded"} <= actions


def test_unapproved_requests_cannot_be_ordered(
    api: TestClient, boq: Boq, se: Who, buyer: Who, supplier: Supplier
) -> None:
    """BR-05."""
    created = raise_request(api, boq, se)

    response = order(api, buyer, supplier, created["id"])

    assert response.status_code == 422
    assert response.json()["error"]["details"] == [{"rule": "BR-05"}]


def test_order_price_cannot_exceed_the_approved_price(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier
) -> None:
    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "approve")

    response = order(api, buyer, supplier, created["id"], unit_price="2000.01")

    assert response.status_code == 422
    assert "above the approved price" in response.json()["error"]["message"]


def test_a_request_is_ordered_only_once(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier
) -> None:
    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "approve")
    assert order(api, buyer, supplier, created["id"]).status_code == 201

    assert order(api, buyer, supplier, created["id"]).status_code == 422  # no longer approved


def test_orders_need_an_active_supplier_one_project_and_a_sensible_date(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier, db: Session
) -> None:
    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "approve")
    bad_date = api.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": str(supplier.id),
            "expected_delivery": needed_by(-1),
            "lines": [{"request_id": created["id"]}],
        },
        headers=buyer.headers,
    )
    duplicate_lines = api.post(
        "/api/v1/purchase-orders",
        json={"supplier_id": str(supplier.id), "expected_delivery": needed_by(3),
              "lines": [{"request_id": created["id"]}, {"request_id": created["id"]}]},
        headers=buyer.headers,
    )  # fmt: skip
    supplier.is_active = False
    db.commit()

    assert bad_date.status_code == 422
    assert duplicate_lines.status_code == 422
    assert order(api, buyer, supplier, created["id"]).status_code == 422


def test_deliveries_cannot_exceed_what_was_ordered(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier
) -> None:
    created = raise_request(api, boq, se, quantity="10")
    decide(api, created["id"], qs, "approve")
    po = order(api, buyer, supplier, created["id"]).json()

    over = deliver(api, buyer, po["id"], created["id"], "10.001")
    future = api.post(
        f"/api/v1/purchase-orders/{po['id']}/deliveries",
        json={"request_id": created["id"], "quantity": "1", "delivered_on": needed_by(2)},
        headers=buyer.headers,
    )
    wrong_line = deliver(api, buyer, po["id"], "00000000-0000-4000-8000-000000000000", "1")

    assert over.status_code == 422
    assert "remain to be delivered" in over.json()["error"]["message"]
    assert future.status_code == 422
    assert wrong_line.status_code == 422


def test_only_procurement_orders_and_receives(
    api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who, supplier: Supplier
) -> None:
    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "approve")

    for who in (se, qs, pm):
        assert order(api, who, supplier, created["id"]).status_code == 403


# --- Scope, lists and budget ----------------------------------------------------------------------------


def test_requests_on_other_sites_are_invisible(
    api: TestClient, boq: Boq, se: Who, team: Callable[..., Who], make_site: Callable[..., Site]
) -> None:
    created = raise_request(api, boq, se)
    elsewhere = make_site("KDY-02")
    outsider_qs = team(Role.QUANTITY_SURVEYOR, sites=[elsewhere])
    outsider_se = team(Role.SITE_ENGINEER, sites=[elsewhere])

    assert api.get(f"{URL}/{created['id']}", headers=outsider_qs.headers).status_code == 404
    assert decide(api, created["id"], outsider_qs, "approve").status_code == 404
    assert api.get(URL, headers=outsider_qs.headers).json()["total"] == 0
    assert api.post(URL, json=request_body(boq), headers=outsider_se.headers).status_code == 404
    assert (
        api.get(f"/api/v1/projects/{boq.project.id}/budget", headers=outsider_qs.headers).status_code == 404
    )


def test_list_has_pipeline_counts_and_filters(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who
) -> None:
    first = raise_request(api, boq, se, quantity="10")
    raise_request(api, boq, se, quantity="10")
    raise_request(api, boq, se, quantity="10", unit_price="3000")
    decide(api, first["id"], qs, "approve")

    everything = api.get(URL, headers=qs.headers).json()
    pending = api.get(URL, params={"status": "requested"}, headers=qs.headers).json()
    company = api.get(URL, headers=buyer.headers).json()

    assert everything["total"] == 3
    assert everything["counts"]["requested"] == 2
    assert everything["counts"]["approved"] == 1
    assert everything["counts"]["delivered"] == 0
    assert [r["number"] for r in pending["items"]] == ["MR-0003", "MR-0002"]
    assert company["total"] == 3  # procurement works company-wide
    assert api.get(URL, params={"mine": "true"}, headers=qs.headers).json()["total"] == 0
    assert api.get(URL, params={"status": "lost"}, headers=qs.headers).status_code == 422


def test_boq_item_picker_shows_what_is_left(api: TestClient, boq: Boq, se: Who) -> None:
    raise_request(api, boq, se, quantity="250")

    options = api.get(f"/api/v1/projects/{boq.project.id}/boq-items", headers=se.headers).json()

    cement = next(o for o in options if o["item_code"] == "A.1")
    assert (cement["boq_quantity"], cement["requested_quantity"], cement["budget_rate"]) == (
        "1000.000",
        "250.000",
        "2000.00",
    )


def test_budget_is_internal(api: TestClient, boq: Boq, team: Callable[..., Who], se: Who, buyer: Who) -> None:
    """TC-07 pattern: clients (and roles without cost access) never see internal costs."""
    client = team(Role.CLIENT)
    url = f"/api/v1/projects/{boq.project.id}/budget"

    assert api.get(url, headers=client.headers).status_code == 403
    assert api.get(url, headers=se.headers).status_code == 403
    assert api.get(url, headers=buyer.headers).status_code == 403


def test_boq_cannot_be_replaced_once_requests_exist(
    api: TestClient, boq: Boq, se: Who, team: Callable[..., Who]
) -> None:
    raise_request(api, boq, se)
    surveyor = team(Role.QUANTITY_SURVEYOR)
    csv = b"Section Code,Section Name,Item Code,Description,Unit,Quantity,Rate\nA,P,A.1,Setup,item,1,9\n"

    response = api.post(
        f"/api/v1/projects/{boq.project.id}/boq/import",
        files={"file": ("boq.csv", csv)},
        params={"dry_run": "false"},
        headers=surveyor.headers,
    )

    assert response.status_code == 422
    assert "material requests already refer" in response.json()["error"]["message"]


# --- Suppliers -----------------------------------------------------------------------------------------


def test_procurement_manages_suppliers(api: TestClient, buyer: Who, qs: Who, supplier: Supplier) -> None:
    created = api.post(
        "/api/v1/suppliers",
        json={"name": "Southern Steel Traders", "phone": "077 123 4567", "email": "sales@steel.example"},
        headers=buyer.headers,
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    assert (
        api.post(
            "/api/v1/suppliers", json={"name": "Kelani Building Supplies"}, headers=buyer.headers
        ).status_code
        == 409
    )
    assert (
        api.post(
            "/api/v1/suppliers", json={"name": "X", "phone": "call me"}, headers=buyer.headers
        ).status_code
        == 422
    )
    assert api.post("/api/v1/suppliers", json={"name": "Q Supplies"}, headers=qs.headers).status_code == 403
    assert (
        api.patch(f"/api/v1/suppliers/{sid}", json={"is_active": False}, headers=buyer.headers).json()[
            "is_active"
        ]
        is False
    )
    assert (
        api.patch(f"/api/v1/suppliers/{sid}", json={"name": None}, headers=buyer.headers).status_code == 422
    )

    visible = [s["name"] for s in api.get("/api/v1/suppliers", headers=qs.headers).json()]
    everything = [
        s["name"]
        for s in api.get(
            "/api/v1/suppliers", params={"include_inactive": "true"}, headers=buyer.headers
        ).json()
    ]
    hidden_for_qs = [
        s["name"]
        for s in api.get("/api/v1/suppliers", params={"include_inactive": "true"}, headers=qs.headers).json()
    ]
    assert visible == ["Kelani Building Supplies"]
    assert everything == ["Kelani Building Supplies", "Southern Steel Traders"]
    assert hidden_for_qs == visible


def test_purchase_orders_are_listed_and_scoped(
    api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who, buyer: Who, supplier: Supplier,
    team: Callable[..., Who], make_site: Callable[..., Site],
) -> None:  # fmt: skip
    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "approve")
    po = order(api, buyer, supplier, created["id"]).json()

    assert [p["number"] for p in api.get("/api/v1/purchase-orders", headers=pm.headers).json()] == ["PO-0001"]
    assert api.get("/api/v1/purchase-orders", params={"status": "delivered"}, headers=pm.headers).json() == []
    detail = api.get(f"/api/v1/purchase-orders/{po['id']}", headers=pm.headers).json()
    assert detail["lines"][0]["request_number"] == "MR-0001"
    outsider = team(Role.PROJECT_MANAGER, sites=[make_site("KDY-02")])
    assert api.get(f"/api/v1/purchase-orders/{po['id']}", headers=outsider.headers).status_code == 404
    assert api.get("/api/v1/purchase-orders", headers=outsider.headers).json() == []


def test_document_numbers_keep_counting(api: TestClient, boq: Boq, se: Who) -> None:
    numbers = [raise_request(api, boq, se, quantity="1")["number"] for _ in range(3)]

    assert numbers == ["MR-0001", "MR-0002", "MR-0003"]


def test_amounts_are_exact(api: TestClient, boq: Boq, se: Who) -> None:
    created = raise_request(api, boq, se, quantity="3.333", unit_price="1999.99")

    assert Decimal(created["amount"]) == Decimal("6665.97")  # type: ignore[arg-type]
