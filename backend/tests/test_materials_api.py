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
from app.models import AuditLog, MaterialRequest, Notification, PurchaseOrder, Site, Supplier, User
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
    # The engineer's response carries no prices or amounts, and only the quantity rule.
    assert "amount" not in created
    assert "unit_price" not in created
    assert created["rules"]["blocked"] is False  # type: ignore[index]
    assert [r["rule"] for r in created["rules"]["results"]] == ["BR-02"]  # type: ignore[index]
    assert "budget_rate" not in created["rules"]  # type: ignore[operator]
    assert created["history"][0]["action"] == "submit"  # type: ignore[index]
    # The QS sees the price as pending, with the budgeted rate as reference for the quote.
    for_qs = api.get(f"{URL}/{created['id']}", headers=qs.headers).json()
    assert (for_qs["unit_price"], for_qs["amount"]) == (None, None)
    assert [(r["rule"], r["severity"]) for r in for_qs["rules"]["results"]] == [
        ("BR-02", "pass"), ("BR-01", "pending"), ("BR-13", "pending"),
    ]  # fmt: skip
    assert for_qs["rules"]["budget_rate"] == "2000.00"
    assert for_qs["rules"]["routed_by"] == []
    assert created["actions"] == ["cancel"]  # the requester can only cancel
    [note] = notes_for(db, qs.user)
    assert note.kind == "request_pending"
    assert note.link == f"/materials/{created['id']}"
    assert notes_for(db, pm.user) == []
    assert db.scalar(select(AuditLog).where(AuditLog.action == "material_request.created")) is not None


def test_request_six_percent_over_budget_goes_to_the_pm(
    api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who
) -> None:
    """TC-02 (BR-01): the QS prices the request 6% over the budgeted rate at the QS check."""
    created = raise_request(api, boq, se)

    approved = decide(api, created["id"], qs, "approve", unit_price="2120")
    body = approved.json()
    assert body["status"] == "pm_approval"  # the QS check passes it on, it does not approve it
    assert body["unit_price"] == "2120.00"
    assert body["rules"]["routed_by"] == ["BR-01"]
    br01 = next(r for r in body["rules"]["results"] if r["rule"] == "BR-01")
    assert "6.0% above the budgeted rate" in br01["message"]
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
    api: TestClient, boq: Boq, qs: Who, db: Session
) -> None:
    response = api.post(
        f"{URL}/check",
        json={
            "project_id": str(boq.project.id),
            "boq_item_id": str(boq.cement.id),
            "quantity": "2000",
            "unit_price": "2500",
        },
        headers=qs.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["blocked"] is True
    assert body["approval_level"] == "pm"
    assert body["routed_by"] == ["BR-01", "BR-13"]
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
    other = team(Role.QUANTITY_SURVEYOR)
    assert decide(api, created["id"], other, "approve", unit_price="2000").json()["status"] == "approved"


def test_pm_who_raised_a_request_cannot_approve_it_either(
    api: TestClient, boq: Boq, pm: Who, qs: Who, team: Callable[..., Who]
) -> None:
    created = raise_request(api, boq, pm, unit_price="2500")  # 25% over: needs a PM
    decide(api, created["id"], qs, "approve")  # the PM priced it

    assert decide(api, created["id"], pm, "approve").status_code == 403
    assert decide(api, created["id"], team(Role.PROJECT_MANAGER), "approve").json()["status"] == "approved"


def test_invalid_transitions_are_refused(api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who) -> None:
    created = raise_request(api, boq, se)
    assert decide(api, created["id"], pm, "approve").status_code == 403  # the PM cannot skip the QS check
    decide(api, created["id"], qs, "approve", unit_price="2000")

    again = decide(api, created["id"], qs, "approve", unit_price="2000")
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
    late = raise_request(api, boq, se, quantity="20")  # fits the budget today
    # Meanwhile steel is priced far over budget and approved, filling the section's budget line.
    big = raise_request(api, boq, team(Role.SITE_ENGINEER), boq_item_id=str(boq.steel.id), quantity="10")
    decide(api, big["id"], qs, "approve", unit_price="460000")
    decide(api, big["id"], team(Role.PROJECT_MANAGER), "approve")

    response = decide(api, late["id"], qs, "approve", unit_price="2000")

    body = response.json()
    assert body["status"] == "pm_approval"
    assert body["approval_level"] == "pm"
    # The price is on budget (BR-01 passes); the section's committed cost is the reason (BR-13).
    assert body["rules"]["routed_by"] == ["BR-13"]
    # Once the PM has approved it, ordering at the approved price does not send it back again.
    decide(api, late["id"], team(Role.PROJECT_MANAGER), "approve")
    ordered = order(api, buyer, supplier, late["id"])
    assert ordered.status_code == 201, ordered.text
    assert ordered.json()["returned"] == []


# --- Ordering and delivery ----------------------------------------------------------------------------


def test_full_flow_from_site_to_delivery_updates_the_budget(
    api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who, buyer: Who, supplier: Supplier, db: Session
) -> None:
    """Phase 5 "Done when": correct routing, and the budget figures update by themselves."""
    budget_url = f"/api/v1/projects/{boq.project.id}/budget"
    created = raise_request(api, boq, se, quantity="100")

    def figures() -> tuple[str, ...]:
        totals = api.get(budget_url, headers=pm.headers).json()["totals"]
        return tuple(totals[k] for k in ("approved", "on_order", "spent", "committed", "remaining"))

    # A pending request (price not yet quoted, not approved) commits nothing.
    assert figures() == ("0.00", "0.00", "0.00", "0.00", "4400000.00")
    decide(api, created["id"], qs, "approve", unit_price="2000")

    assert figures() == ("200000.00", "0.00", "0.00", "200000.00", "4200000.00")
    assert [n.kind for n in notes_for(db, buyer.user)] == ["request_ready_to_order"]
    ready = api.get("/api/v1/purchase-orders/ready", headers=buyer.headers).json()
    assert [r["number"] for r in ready] == ["MR-0001"]

    po = order(api, buyer, supplier, created["id"], unit_price="1950")
    assert po.status_code == 201, po.text
    assert po.json()["returned"] == []
    po_body = po.json()["order"]
    assert po_body["number"] == "PO-0001"
    assert po_body["total"] == "195000.00"
    # Counted once, now at the order value: committed moves from the approved to the PO amount.
    assert figures() == ("0.00", "195000.00", "0.00", "195000.00", "4205000.00")

    part = deliver(api, buyer, po_body["id"], created["id"], "40")
    assert part.status_code == 201, part.text
    assert part.json()["status"] == "part_delivered"
    assert figures() == ("0.00", "117000.00", "78000.00", "195000.00", "4205000.00")

    done = deliver(api, buyer, po_body["id"], created["id"], "60").json()
    assert done["status"] == "delivered"
    assert figures() == ("0.00", "0.00", "195000.00", "195000.00", "4205000.00")
    line = api.get(budget_url, headers=pm.headers).json()["lines"][0]
    assert (line["committed"], line["remaining"]) == ("195000.00", "4205000.00")

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


def test_order_price_up_to_five_percent_above_approval_is_accepted(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier
) -> None:
    """BR-14 boundary: exactly 5% above the approved price is still ordered."""
    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "approve", unit_price="2000")

    response = order(api, buyer, supplier, created["id"], unit_price="2100")

    assert response.status_code == 201, response.text
    assert response.json()["order"]["total"] == "210000.00"
    assert response.json()["returned"] == []


def test_order_price_more_than_five_percent_above_approval_goes_back_to_the_pm(
    api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who, buyer: Who, supplier: Supplier, db: Session
) -> None:
    """BR-14: the quote is too far above the approved price, so the PM must approve it again."""
    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "approve", unit_price="2000")

    response = order(api, buyer, supplier, created["id"], unit_price="2100.01")

    assert response.status_code == 200, response.text  # nothing ordered
    body = response.json()
    assert body["order"] is None
    [returned] = body["returned"]
    assert (returned["number"], returned["unit_price"]) == ("MR-0001", "2100.01")
    assert [r["rule"] for r in returned["rules"]] == ["BR-14"]
    assert "above the approved price (limit 5%)" in returned["rules"][0]["message"]

    request = api.get(f"{URL}/{created['id']}", headers=pm.headers).json()
    assert (request["status"], request["approval_level"]) == ("pm_approval", "pm")
    assert request["unit_price"] == "2100.01"  # to be approved at the quoted price
    assert request["history"][-1]["action"] == "return_for_approval"
    assert request["history"][-1]["comment"] == (
        "Sent back for project manager approval: the quoted price is more than 5% above the approved "
        "price (BR-14)."
    )
    assert request["actions"] == ["approve", "reject", "request_change"]
    [note] = [n for n in notes_for(db, pm.user) if n.kind == "request_pending"]
    assert note.title == "MR-0001 is back for your approval"
    assert db.scalar(
        select(AuditLog).where(AuditLog.action == "material_request.returned_for_approval")
    ) is not None  # fmt: skip
    assert db.scalar(select(func.count(PurchaseOrder.id))) == 0
    # The engineer sees the history step but not the price.
    mine = api.get(f"{URL}/{created['id']}", headers=se.headers).json()
    assert "unit_price" not in mine
    assert mine["history"][-1]["action"] == "return_for_approval"

    # Approved again by the PM at the quoted price, it can now be ordered at that price.
    assert decide(api, created["id"], pm, "approve").json()["status"] == "approved"
    again = order(api, buyer, supplier, created["id"], unit_price="2100.01")
    assert again.status_code == 201, again.text
    assert again.json()["order"]["total"] == "210001.00"


def test_order_without_a_price_uses_the_approved_price(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier
) -> None:
    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "approve", unit_price="1980")

    response = order(api, buyer, supplier, created["id"])

    assert response.json()["order"]["lines"][0]["unit_price"] == "1980.00"


def test_a_request_is_ordered_only_once(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier
) -> None:
    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "approve", unit_price="2000")
    assert order(api, buyer, supplier, created["id"]).status_code == 201

    assert order(api, buyer, supplier, created["id"]).status_code == 422  # no longer approved


def test_orders_need_an_active_supplier_one_project_and_a_sensible_date(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier, db: Session
) -> None:
    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "approve", unit_price="2000")
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
    decide(api, created["id"], qs, "approve", unit_price="2000")
    po = order(api, buyer, supplier, created["id"]).json()["order"]

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
    decide(api, created["id"], qs, "approve", unit_price="2000")

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
    raise_request(api, boq, se, quantity="10")
    decide(api, first["id"], qs, "approve", unit_price="2000")

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


def test_boq_item_picker_shows_what_is_left(api: TestClient, boq: Boq, se: Who, qs: Who) -> None:
    raise_request(api, boq, se, quantity="250")
    url = f"/api/v1/projects/{boq.project.id}/boq-items"

    for_engineer = next(o for o in api.get(url, headers=se.headers).json() if o["item_code"] == "A.1")
    for_qs = next(o for o in api.get(url, headers=qs.headers).json() if o["item_code"] == "A.1")

    assert for_engineer == {
        "id": str(boq.cement.id), "item_code": "A.1", "description": "Cement, 50 kg bags", "unit": "bag",
        "section_code": "A", "section_name": "Materials", "boq_quantity": "1000.000",
        "requested_quantity": "250.000", "remaining_quantity": "750.000",
    }  # fmt: skip
    assert for_qs["budget_rate"] == "2000.00"


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
    decide(api, created["id"], qs, "approve", unit_price="2000")
    po = order(api, buyer, supplier, created["id"]).json()["order"]

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


def test_amounts_are_exact(api: TestClient, boq: Boq, team: Callable[..., Who]) -> None:
    created = raise_request(api, boq, team(Role.PROJECT_MANAGER), quantity="3.333", unit_price="1999.99")

    assert Decimal(created["amount"]) == Decimal("6665.97")  # type: ignore[arg-type]


# --- Prices: only roles that see rates set them ------------------------------------------------------


def test_engineers_cannot_send_prices(api: TestClient, boq: Boq, se: Who, qs: Who, db: Session) -> None:
    with_price = api.post(URL, json=request_body(boq, unit_price="1500"), headers=se.headers)
    check = api.post(
        f"{URL}/check",
        json={
            "project_id": str(boq.project.id),
            "boq_item_id": str(boq.cement.id),
            "quantity": "1",
            "unit_price": "9",
        },
        headers=se.headers,
    )

    assert with_price.status_code == 422
    assert with_price.json()["error"]["code"] == "price_not_allowed"
    assert check.json()["error"]["code"] == "price_not_allowed"
    assert db.scalar(select(func.count(MaterialRequest.id))) == 0

    created = raise_request(api, boq, se)
    decide(api, created["id"], qs, "request_change", "Fewer, please.")
    edit = api.patch(f"{URL}/{created['id']}", json={"unit_price": "1"}, headers=se.headers)
    assert edit.json()["error"]["code"] == "price_not_allowed"


def test_engineer_check_shows_the_quantity_rule_only(api: TestClient, boq: Boq, se: Who) -> None:
    response = api.post(
        f"{URL}/check",
        json={"project_id": str(boq.project.id), "boq_item_id": str(boq.cement.id), "quantity": "10"},
        headers=se.headers,
    )

    body = response.json()
    assert response.status_code == 200
    assert [r["rule"] for r in body["results"]] == ["BR-02"]
    assert set(body) == {"approval_level", "blocked", "results", "routed_by"}


def test_only_the_qs_sets_a_price_and_only_when_approving(
    api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who
) -> None:
    created = raise_request(api, boq, se)

    rejecting = decide(api, created["id"], qs, "reject", "No.", unit_price="1900")
    assert rejecting.status_code == 422
    priced = decide(api, created["id"], qs, "approve", unit_price="1900")
    assert priced.json()["unit_price"] == "1900.00"
    assert priced.json()["status"] == "approved"

    second = raise_request(api, boq, se)
    decide(api, second["id"], qs, "approve", unit_price="2500")  # 25% over: PM approval
    assert decide(api, second["id"], pm, "approve", unit_price="2000").status_code == 422


def test_items_without_a_rate_can_be_requested_and_the_qs_prices_them(
    api: TestClient, boq: Boq, se: Who, qs: Who, db: Session
) -> None:
    """The price is pending until the QS check, so a missing BOQ rate does not stop the site."""
    boq.line.budget_amount = Decimal(0)
    boq.cement.rate = Decimal(0)
    db.commit()

    created = raise_request(api, boq, se)
    for_qs = api.get(f"{URL}/{created['id']}", headers=qs.headers).json()

    assert for_qs["unit_price"] is None
    assert for_qs["rules"]["budget_rate"] == "0.00"
    approved = decide(api, created["id"], qs, "approve", unit_price="2000").json()
    assert approved["status"] == "pm_approval"  # no budget at all: BR-01 and BR-13 both fire
    assert approved["rules"]["routed_by"] == ["BR-01", "BR-13"]


# --- Price pending: the QS enters the quoted price -------------------------------------------------


def test_engineer_requests_start_with_the_price_pending(
    api: TestClient, boq: Boq, se: Who, db: Session
) -> None:
    created = raise_request(api, boq, se)

    request = db.get(MaterialRequest, created["id"])
    assert request is not None
    assert request.unit_price is None


def test_qs_cannot_approve_until_the_price_is_entered(
    api: TestClient, boq: Boq, se: Who, qs: Who, db: Session
) -> None:
    created = raise_request(api, boq, se)

    response = decide(api, created["id"], qs, "approve")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "price_required"
    assert "quoted unit price" in response.json()["error"]["message"]
    assert db.get(MaterialRequest, created["id"]).status == "requested"  # type: ignore[union-attr]
    # Rejecting or asking for a change does not need a price.
    assert decide(api, created["id"], qs, "request_change", "Which grade?").status_code == 200


def test_pending_requests_are_not_ready_to_order_and_cannot_be_ordered(
    api: TestClient, boq: Boq, se: Who, buyer: Who, supplier: Supplier
) -> None:
    created = raise_request(api, boq, se)

    assert api.get("/api/v1/purchase-orders/ready", headers=buyer.headers).json() == []
    assert order(api, buyer, supplier, created["id"], unit_price="2000").status_code == 422


# --- BR-13 is cumulative: two requests that fit alone but not together ------------------------------


def test_two_requests_that_fit_alone_exceed_the_line_together_at_approval(
    api: TestClient, boq: Boq, se: Who, qs: Who
) -> None:
    """Budget line 4,400,000 with steel 2,400,000 approved: two cement requests of 1,050,000 (500 bags
    at 2,100, inside BR-01's 5%) each fit beside the steel, but not together (4,500,000)."""
    steel = raise_request(api, boq, se, boq_item_id=str(boq.steel.id), quantity="10")
    assert decide(api, steel["id"], qs, "approve", unit_price="240000").json()["status"] == "approved"
    first = raise_request(api, boq, se, quantity="500")
    second = raise_request(api, boq, se, quantity="500")

    def preview() -> list[str]:
        body = {"project_id": str(boq.project.id), "boq_item_id": str(boq.cement.id), "quantity": "500",
                "unit_price": "2100"}  # fmt: skip
        routed: list[str] = api.post(f"{URL}/check", json=body, headers=qs.headers).json()["routed_by"]
        return routed

    # Each fits alone: pending requests are not committed, so neither counts the other yet.
    assert preview() == []

    one = decide(api, first["id"], qs, "approve", unit_price="2100").json()
    two = decide(api, second["id"], qs, "approve", unit_price="2100").json()

    assert (one["status"], one["rules"]["routed_by"]) == ("approved", [])
    assert (two["status"], two["rules"]["routed_by"]) == ("pm_approval", ["BR-13"])
    br13 = next(r for r in two["rules"]["results"] if r["rule"] == "BR-13")
    assert br13["facts"]["line_committed"] == "3450000.00"


def _two_approved_requests(api: TestClient, boq: Boq, se: Who, qs: Who) -> tuple[str, str]:
    """Budget line 4,400,000: steel 2,400,000 and cement 1,900,000 approved (4,300,000 committed)."""
    steel = raise_request(api, boq, se, boq_item_id=str(boq.steel.id), quantity="10")
    cement = raise_request(api, boq, se, quantity="950")
    assert decide(api, steel["id"], qs, "approve", unit_price="240000").json()["status"] == "approved"
    assert decide(api, cement["id"], qs, "approve", unit_price="2000").json()["status"] == "approved"
    return str(steel["id"]), str(cement["id"])


def test_two_lines_that_fit_alone_exceed_the_line_together_at_po_issue(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier, db: Session
) -> None:
    """Quotes 3% up (inside BR-14): steel 2,472,000, cement 1,957,000.

    Each fits beside the other's approved amount (4,372,000 and 4,357,000), but together they reach
    4,429,000 against 4,400,000. The first line is ordered; the second goes back to the PM (BR-13).
    """
    steel, cement = _two_approved_requests(api, boq, se, qs)

    response = api.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": str(supplier.id),
            "expected_delivery": needed_by(7),
            "lines": [
                {"request_id": steel, "unit_price": "247200"},
                {"request_id": cement, "unit_price": "2060"},
            ],
        },
        headers=buyer.headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert [line["request_id"] for line in body["order"]["lines"]] == [steel]
    [returned] = body["returned"]
    assert returned["request_id"] == cement
    assert [r["rule"] for r in returned["rules"]] == ["BR-13"]
    sent_back = db.get(MaterialRequest, cement)
    assert sent_back is not None
    assert (sent_back.status, sent_back.unit_price) == ("pm_approval", Decimal("2060.00"))


def test_two_requests_ordered_on_separate_orders_are_checked_together(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier, db: Session
) -> None:
    steel, cement = _two_approved_requests(api, boq, se, qs)

    first = order(api, buyer, supplier, steel, unit_price="247200")
    second = order(api, buyer, supplier, cement, unit_price="2060")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["order"] is None
    assert [r["rule"] for r in second.json()["returned"][0]["rules"]] == ["BR-13"]
    assert api.get(f"{URL}/{cement}", headers=qs.headers).json()["status"] == "pm_approval"


def test_pm_approved_requests_are_not_returned_for_the_same_excess(
    api: TestClient, boq: Boq, se: Who, qs: Who, pm: Who, buyer: Who, supplier: Supplier
) -> None:
    steel, cement = _two_approved_requests(api, boq, se, qs)
    order(api, buyer, supplier, steel, unit_price="247200")
    order(api, buyer, supplier, cement, unit_price="2060")  # back to the PM (BR-13)
    assert decide(api, cement, pm, "approve").json()["status"] == "approved"

    again = order(api, buyer, supplier, cement, unit_price="2060")

    assert again.status_code == 201, again.text
    assert again.json()["returned"] == []
