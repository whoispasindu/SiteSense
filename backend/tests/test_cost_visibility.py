"""Site engineers never receive rates or amounts; PM, QS and procurement do.

The engineer test walks every endpoint an engineer can call, after a full request-to-delivery flow
so that orders, deliveries and rule results all exist, and fails if any cost field appears
anywhere in a response, at any depth.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import clock
from app.core.permissions import Permission, Role, has_permission
from app.models import Supplier
from tests.materials_fixtures import Boq, Who, decide, needed_by, raise_request

# Every key that carries a rate, price or amount anywhere in the API.
COST_KEYS = frozenset(
    {
        "contract_value", "boq_total", "budget_total", "amount", "budget_amount", "budget_line_id",
        "rate", "unit_price", "budget_rate", "total", "budget", "approved", "committed", "spent",
        "remaining", "forecast", "variance", "boq_amount", "line_budget", "line_committed",
        "line_after_request", "line_over", "price_over",
    }
)  # fmt: skip
COST_RULES = {"BR-01", "BR-13"}


def walk(value: Any) -> Iterator[tuple[str, Any]]:
    """Every (key, value) pair in a JSON document, at any depth."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key, inner
            yield from walk(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from walk(inner)


# Names also used for counts and percentages (a list's "total", a pipeline count of "approved", the
# schedule's "variance" in points). Money always travels as a decimal string, so these are leaks only
# when the value is a string.
AMBIGUOUS = frozenset({"total", "approved", "variance", "remaining"})


def cost_leaks(document: Any) -> list[str]:
    leaks = [
        key
        for key, value in walk(document)
        if key in COST_KEYS and (key not in AMBIGUOUS or isinstance(value, str))
    ]
    leaks += [f"rule {v}" for key, v in walk(document) if key == "rule" and v in COST_RULES]
    return leaks


@pytest.fixture
def flow(
    api: TestClient, boq: Boq, se: Who, qs: Who, buyer: Who, supplier: Supplier, db: Session
) -> dict[str, str]:
    """One delivered request, one waiting at the QS check, one daily report and a programme task."""
    delivered = raise_request(api, boq, se, quantity="10")
    decide(api, delivered["id"], qs, "approve", unit_price="1950")
    po = api.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": str(supplier.id),
            "expected_delivery": needed_by(3),
            "lines": [{"request_id": delivered["id"]}],
        },
        headers=buyer.headers,
    ).json()
    api.post(
        f"/api/v1/purchase-orders/{po['id']}/deliveries",
        json={
            "request_id": delivered["id"],
            "quantity": "10",
            "delivered_on": clock.site_today().isoformat(),
        },
        headers=buyer.headers,
    )
    pending = raise_request(api, boq, se, quantity="5")
    return {
        "project": str(boq.project.id),
        "delivered": str(delivered["id"]),
        "pending": str(pending["id"]),
        "po": po["id"],
    }


def engineer_calls(api: TestClient, se: Who, boq: Boq, ids: dict[str, str]) -> dict[str, Any]:
    p = ids["project"]
    get = {
        "projects": "/api/v1/projects",
        "project": f"/api/v1/projects/{p}",
        "boq": f"/api/v1/projects/{p}/boq",
        "boq-items": f"/api/v1/projects/{p}/boq-items",
        "schedule": "/api/v1/schedule/summary",
        "requests": "/api/v1/material-requests",
        "request delivered": f"/api/v1/material-requests/{ids['delivered']}",
        "request pending": f"/api/v1/material-requests/{ids['pending']}",
        "orders": "/api/v1/purchase-orders",
        "order": f"/api/v1/purchase-orders/{ids['po']}",
        "suppliers": "/api/v1/suppliers",
        "reports today": "/api/v1/reports/today",
        "notifications": "/api/v1/notifications",
    }
    responses: dict[str, Any] = {}
    for name, url in get.items():
        response = api.get(url, headers=se.headers)
        assert response.status_code == 200, f"{name}: {response.text}"
        responses[name] = response.json()
    created = api.post(
        "/api/v1/material-requests",
        json={"project_id": p, "boq_item_id": str(boq.steel.id), "quantity": "1", "needed_by": needed_by()},
        headers=se.headers,
    )
    assert created.status_code == 201, created.text
    responses["create"] = created.json()
    responses["check"] = api.post(
        "/api/v1/material-requests/check",
        json={"project_id": p, "boq_item_id": str(boq.cement.id), "quantity": "1"},
        headers=se.headers,
    ).json()
    responses["cancel"] = decide(api, created.json()["id"], se, "cancel").json()
    return responses


def test_engineer_responses_contain_no_cost_fields(
    api: TestClient, boq: Boq, se: Who, flow: dict[str, str]
) -> None:
    responses = engineer_calls(api, se, boq, flow)

    leaks = {name: cost_leaks(body) for name, body in responses.items() if cost_leaks(body)}
    assert leaks == {}
    # The engineer still gets what the screens need: quantities, requested so far and remaining.
    item = responses["boq"]["sections"][0]["items"][0]
    assert {"quantity", "requested_quantity", "remaining_quantity"} <= set(item)
    assert responses["request delivered"]["order"]["delivered_quantity"] == "10.000"


@pytest.mark.parametrize("role", [Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.PROCUREMENT_OFFICER])
def test_rate_readers_receive_cost_fields(
    api: TestClient, boq: Boq, flow: dict[str, str], team: Callable[..., Who], role: Role
) -> None:
    who = team(role)
    p = flow["project"]

    project = api.get(f"/api/v1/projects/{p}", headers=who.headers).json()
    boq_items = api.get(f"/api/v1/projects/{p}/boq", headers=who.headers).json()
    request = api.get(f"/api/v1/material-requests/{flow['delivered']}", headers=who.headers).json()
    order = api.get(f"/api/v1/purchase-orders/{flow['po']}", headers=who.headers).json()

    assert project["contract_value"] == "10000000.00"
    assert boq_items["sections"][0]["items"][0]["rate"] == "2500.00"
    assert (request["unit_price"], request["amount"]) == ("1950.00", "19500.00")
    assert {r["rule"] for r in request["rules"]["results"]} == {"BR-02", "BR-01", "BR-13"}
    assert request["order"]["amount"] == "19500.00"
    assert order["total"] == "19500.00"


def test_clients_reach_no_cost_endpoint(api: TestClient, boq: Boq, team: Callable[..., Who]) -> None:
    client = team(Role.CLIENT)
    p = str(boq.project.id)

    for url in (
        "/api/v1/projects", f"/api/v1/projects/{p}", f"/api/v1/projects/{p}/boq",
        f"/api/v1/projects/{p}/budget", "/api/v1/material-requests", "/api/v1/purchase-orders",
        "/api/v1/schedule/summary",
    ):  # fmt: skip
        assert api.get(url, headers=client.headers).status_code == 403, url


def test_the_permission_table_matches() -> None:
    """Rates and amounts: PM, QS and procurement only."""
    readers = {role for role in Role if has_permission(role, Permission.RATES_READ)}

    assert readers == {Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.PROCUREMENT_OFFICER}


def test_the_leak_detector_works() -> None:
    assert cost_leaks({"a": [{"b": {"unit_price": "1"}}]}) == ["unit_price"]
    assert cost_leaks({"results": [{"rule": "BR-13"}]}) == ["rule BR-13"]
    assert cost_leaks({"quantity": "1", "remaining_quantity": "2"}) == []
    assert cost_leaks({"total": 3, "counts": {"approved": 1}, "variance": -4.4}) == []
    assert cost_leaks({"total": "19500.00"}) == ["total"]
