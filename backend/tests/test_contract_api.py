"""Phase 8: progress claims (BR-08), variation orders (BR-09, TC-10), the BR-09 limit, cost forecasts."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.permissions import Role
from app.models import AuditLog, BudgetLine, Notification, Project, RiskScore, Site, Task
from app.services import cost_service
from tests.materials_fixtures import Boq, Who, decide, raise_request

D = Decimal


@pytest.fixture
def client_user(team: Callable[..., Who], boq: Boq, db: Session) -> Who:
    client = team(Role.CLIENT)
    client.user.client_projects = [boq.project]  # Phase 12: clients see the projects they are linked to
    db.commit()
    return client


@pytest.fixture
def admin(team: Callable[..., Who]) -> Who:
    return team(Role.ADMIN)


@pytest.fixture
def task(db: Session, boq: Boq) -> Task:
    section_id = boq.cement.section_id
    row = Task(
        project_id=boq.project.id, boq_section_id=section_id, code="T1", name="Level 4 slab",
        planned_start=date(2026, 9, 1), planned_end=date(2026, 11, 30), weight=D(100), position=1,
    )  # fmt: skip
    db.add(row)
    db.commit()
    return row


def section_id(boq: Boq) -> str:
    return str(boq.cement.section_id)


def audits(db: Session, action: str) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


def notes_of(db: Session, who: Who, kind: str) -> list[Notification]:
    return list(
        db.scalars(select(Notification).where(Notification.user_id == who.user.id, Notification.kind == kind))
    )


# --- Progress claims (BR-08) -------------------------------------------------------------------------


def claim_body(boq: Boq, pct: str) -> dict[str, object]:
    return {"sections": [{"section_id": section_id(boq), "certified_pct": pct}], "notes": "Monthly claim"}


def make_claim(api: TestClient, boq: Boq, qs: Who, pct: str) -> dict:  # type: ignore[type-arg]
    response = api.post(
        f"/api/v1/projects/{boq.project.id}/claims", json=claim_body(boq, pct), headers=qs.headers
    )
    assert response.status_code == 201, response.text
    body: dict = response.json()  # type: ignore[type-arg]
    return body


def test_br08_claim_is_calculated_with_retention(
    api: TestClient, db: Session, boq: Boq, qs: Who, pm: Who
) -> None:
    """40% of a LKR 10 M contract: 4,000,000 certified, 200,000 retention, 3,800,000 claimed."""
    check = api.post(
        f"/api/v1/projects/{boq.project.id}/claims/check", json=claim_body(boq, "40"), headers=qs.headers
    ).json()
    claim = make_claim(api, boq, qs, "40")

    assert check["problems"] == []
    assert check["figures"] == claim["figures"]
    figures = claim["figures"]
    assert (figures["certified_value"], figures["retention"], figures["amount"]) == (
        "4000000.00",
        "200000.00",
        "3800000.00",
    )
    assert (figures["certified_pct"], figures["retention_rate"]) == ("40.00", "0.05")
    assert claim["status"] == "submitted"
    assert claim["actions"] == []  # the QS neither approves nor records payment yet
    assert len(notes_of(db, pm, "claim_submitted")) == 1
    assert audits(db, "claim.submitted")[0].details["amount"] == "3800000.00"


def test_br08_previous_claims_are_deducted_once_approved(api: TestClient, boq: Boq, qs: Who, pm: Who) -> None:
    first = make_claim(api, boq, qs, "40")
    approved = api.post(
        f"/api/v1/claims/{first['id']}/decision", json={"decision": "approve"}, headers=pm.headers
    )
    assert approved.json()["status"] == "approved"

    second = make_claim(api, boq, qs, "60")

    assert second["figures"]["previous_claims"] == "3800000.00"
    assert second["figures"]["amount"] == "1900000.00"  # 6,000,000 - 300,000 - 3,800,000
    assert second["lines"][0]["previous_pct"] == "40.00"
    overview = api.get(f"/api/v1/projects/{boq.project.id}/claims", headers=pm.headers).json()
    assert overview["claimed_to_date"] == "3800000.00"
    assert overview["can_create"] is False  # PMs approve claims; they do not make them
    assert [c["number"] for c in overview["claims"]] == [second["number"], first["number"]]


@pytest.mark.parametrize(
    ("pct", "message"), [("30", "below the last approved claim"), ("40", "Nothing to claim")]
)
def test_br08_progress_cannot_go_back_or_claim_nothing(
    api: TestClient, boq: Boq, qs: Who, pm: Who, pct: str, message: str
) -> None:
    first = make_claim(api, boq, qs, "40")
    api.post(f"/api/v1/claims/{first['id']}/decision", json={"decision": "approve"}, headers=pm.headers)

    response = api.post(
        f"/api/v1/projects/{boq.project.id}/claims", json=claim_body(boq, pct), headers=qs.headers
    )

    assert response.status_code == 422
    assert message in response.json()["error"]["message"]


def test_one_claim_waits_for_the_pm_at_a_time(api: TestClient, boq: Boq, qs: Who) -> None:
    make_claim(api, boq, qs, "40")

    response = api.post(
        f"/api/v1/projects/{boq.project.id}/claims", json=claim_body(boq, "50"), headers=qs.headers
    )

    assert response.status_code == 409


def test_a_returned_claim_does_not_count(api: TestClient, db: Session, boq: Boq, qs: Who, pm: Who) -> None:
    claim = make_claim(api, boq, qs, "40")
    url = f"/api/v1/claims/{claim['id']}/decision"

    assert (
        api.post(url, json={"decision": "return"}, headers=pm.headers).status_code == 422
    )  # needs a comment
    returned = api.post(url, json={"decision": "return", "comment": "Use 35%"}, headers=pm.headers).json()
    again = make_claim(api, boq, qs, "35")

    assert returned["status"] == "returned"
    assert again["figures"]["previous_claims"] == "0.00"
    assert notes_of(db, qs, "claim_returned")[0].body == f"{pm.user.full_name}: Use 35%"
    assert api.post(url, json={"decision": "approve"}, headers=pm.headers).status_code == 409


def test_payment_is_recorded_by_the_qs_after_approval(
    api: TestClient, db: Session, boq: Boq, qs: Who, pm: Who
) -> None:
    claim = make_claim(api, boq, qs, "40")
    url = f"/api/v1/claims/{claim['id']}/payment"
    today = clock.site_today()

    assert (
        api.post(url, json={"paid_on": today.isoformat()}, headers=qs.headers).status_code == 409
    )  # not approved
    approved = api.post(
        f"/api/v1/claims/{claim['id']}/decision", json={"decision": "approve"}, headers=pm.headers
    )
    assert approved.json()["actions"] == []  # the PM does not record payments
    assert api.get(f"/api/v1/claims/{claim['id']}", headers=qs.headers).json()["actions"] == [
        "record_payment"
    ]
    future = (today + timedelta(days=1)).isoformat()
    assert api.post(url, json={"paid_on": future}, headers=qs.headers).status_code == 422
    assert api.post(url, json={"paid_on": today.isoformat()}, headers=pm.headers).status_code == 403
    paid = api.post(url, json={"paid_on": today.isoformat()}, headers=qs.headers).json()

    assert (paid["status"], paid["paid_on"]) == ("paid", today.isoformat())
    overview = api.get(f"/api/v1/projects/{boq.project.id}/claims", headers=qs.headers).json()
    assert overview["paid_to_date"] == "3800000.00"
    assert overview["retention_held"] == "200000.00"
    assert audits(db, "claim.paid")[0].details["paid_on"] == today.isoformat()


def test_claims_are_for_the_qs_and_pm_on_the_site(
    api: TestClient, boq: Boq, qs: Who, se: Who, client_user: Who, team: Callable[..., Who],
    make_site: Callable[..., Site],
) -> None:  # fmt: skip
    claim = make_claim(api, boq, qs, "40")
    elsewhere = team(Role.QUANTITY_SURVEYOR, sites=[make_site("KDY-01")])

    for who in (se, client_user):
        assert api.get(f"/api/v1/projects/{boq.project.id}/claims", headers=who.headers).status_code == 403
        assert api.get(f"/api/v1/claims/{claim['id']}", headers=who.headers).status_code == 403
    assert api.get(f"/api/v1/claims/{claim['id']}", headers=elsewhere.headers).status_code == 404
    assert api.get(f"/api/v1/projects/{boq.project.id}/claims", headers=elsewhere.headers).status_code == 404


def test_a_claim_names_only_this_projects_sections(api: TestClient, boq: Boq, qs: Who) -> None:
    body = {"sections": [{"section_id": "00000000-0000-0000-0000-000000000001", "certified_pct": "10"}]}
    duplicate = {"sections": [claim_body(boq, "10")["sections"][0]] * 2}  # type: ignore[index]

    for payload in (body, duplicate):
        response = api.post(f"/api/v1/projects/{boq.project.id}/claims", json=payload, headers=qs.headers)
        assert response.status_code == 422


# --- Variation orders (BR-09, TC-10) -----------------------------------------------------------------


def variation_body(boq: Boq, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "title": "Extra cement for the lift pit",
        "description": "The client moved the lift pit; more concrete is needed.",
        "section_id": section_id(boq),
        "boq_item_id": str(boq.cement.id),
        "quantity_change": "100",
    }
    body.update(overrides)
    return body


def raise_variation(api: TestClient, boq: Boq, who: Who, **overrides: object) -> dict:  # type: ignore[type-arg]
    response = api.post(
        f"/api/v1/projects/{boq.project.id}/variations",
        json=variation_body(boq, **overrides),
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    body: dict = response.json()  # type: ignore[type-arg]
    return body


def test_br09_a_small_qs_variation_goes_to_the_pm_and_applies(
    api: TestClient, db: Session, boq: Boq, qs: Who, pm: Who, se: Who
) -> None:
    """Priced at LKR 90,000 (the limit is 1% of 10 M = 100,000), no time impact: the PM approves."""
    variation = raise_variation(api, boq, qs, contract_change="90000", budget_change="72000")

    assert (variation["status"], variation["approver"]) == ("awaiting_pm", "pm")
    assert (variation["limit"], variation["limit_applied"], variation["needs_client"]) == (
        "100000.00",
        "100000.00",
        False,
    )
    assert len(notes_of(db, pm, "variation_for_pm")) == 1
    approved = api.post(
        f"/api/v1/variations/{variation['id']}/decision", json={"decision": "approve"}, headers=pm.headers
    ).json()

    assert approved["status"] == "approved"
    db.expire_all()
    project = db.get(Project, boq.project.id)
    assert project is not None
    assert project.contract_value == D("10090000.00")
    assert db.get(BudgetLine, boq.line.id).budget_amount == D("4472000.00")  # type: ignore[union-attr]
    # BR-02: the extra 100 bags raise the cement allowance from 1,030 to 1,130.
    blocked = api.post(
        "/api/v1/material-requests/check",
        json={"project_id": str(boq.project.id), "boq_item_id": str(boq.cement.id), "quantity": "1131"},
        headers=se.headers,
    ).json()  # fmt: skip
    assert next(r for r in blocked["results"] if r["rule"] == "BR-02")["severity"] == "block", blocked
    raise_request(api, boq, se, quantity="1130")  # within the varied allowance
    applied = audits(db, "variation.applied")[0]
    assert applied.details["before"]["contract_value"] == "10000000.00"
    assert applied.details["after"]["contract_value"] == "10090000.00"


def test_tc10_client_approves_a_variation_with_time_impact(
    api: TestClient, db: Session, boq: Boq, qs: Who, pm: Who, client_user: Who, task: Task,
    team: Callable[..., Who],
) -> None:  # fmt: skip
    """TC-10: contract value, budget and schedule update; audit entry created."""
    # A client on the same site but not linked to this project (Phase 12) is never told about it.
    neighbour = team(Role.CLIENT)
    variation = raise_variation(
        api,
        boq,
        qs,
        contract_change="50000",
        budget_change="40000",
        time_impact_days=14,
        task_id=str(task.id),
    )
    assert (variation["status"], variation["needs_client"]) == ("awaiting_client", True)
    assert len(notes_of(db, client_user, "variation_for_client")) == 1
    assert notes_of(db, neighbour, "variation_for_client") == []
    seen = api.get(f"/api/v1/client/variations/{variation['id']}", headers=client_user.headers).json()
    assert seen["reason_for_client"] == "It changes the completion date by 14 days."
    assert seen["can_decide"] is True
    end_before = db.get(Project, boq.project.id).planned_end  # type: ignore[union-attr]

    decided = api.post(
        f"/api/v1/variations/{variation['id']}/client-decision",
        json={"decision": "approve"},
        headers=client_user.headers,
    )

    assert decided.status_code == 200, decided.text
    assert (decided.json()["status"], decided.json()["can_decide"]) == ("approved", False)
    db.expire_all()
    project = db.get(Project, boq.project.id)
    assert project is not None
    assert project.contract_value == D("10050000.00")
    assert project.planned_end == end_before + timedelta(days=14)
    assert db.get(Task, task.id).planned_end == date(2026, 12, 14)  # type: ignore[union-attr]
    assert db.get(BudgetLine, boq.line.id).budget_amount == D("4440000.00")  # type: ignore[union-attr]
    [applied] = audits(db, "variation.applied")
    assert applied.actor_id == client_user.user.id
    assert applied.details["after"]["task_end"] == "2026-12-14"
    assert audits(db, "variation.client_decided")[0].details["decision"] == "approve"
    assert db.scalar(select(RiskScore).where(RiskScore.project_id == boq.project.id)) is not None  # re-scored
    assert len(notes_of(db, pm, "variation_approved")) == 1


@pytest.mark.parametrize(
    ("change", "approver"),
    [("100000", "awaiting_pm"), ("100000.01", "awaiting_client"), ("-100000.01", "awaiting_client")],
)
def test_br09_limit_boundary(api: TestClient, boq: Boq, qs: Who, change: str, approver: str) -> None:
    variation = raise_variation(api, boq, qs, contract_change=change, budget_change="0")

    assert variation["status"] == approver


def test_br09_a_pm_variation_is_priced_by_the_qs_and_goes_to_the_client(
    api: TestClient, db: Session, boq: Boq, qs: Who, pm: Who, client_user: Who
) -> None:
    priced_by_pm = api.post(
        f"/api/v1/projects/{boq.project.id}/variations",
        json=variation_body(boq, contract_change="1000", budget_change="800"),
        headers=pm.headers,
    )
    assert priced_by_pm.status_code == 403  # only the QS prices

    variation = raise_variation(api, boq, pm)
    assert (variation["status"], variation["actions"]) == ("awaiting_pricing", ["withdraw"])
    assert len(notes_of(db, qs, "variation_to_price")) == 1
    hidden = api.get(f"/api/v1/client/variations/{variation['id']}", headers=client_user.headers)
    assert hidden.status_code == 404  # not sent to the client yet
    url = f"/api/v1/variations/{variation['id']}/price"
    assert (
        api.post(
            url, json={"contract_change": "1000", "budget_change": "800"}, headers=pm.headers
        ).status_code
        == 403
    )
    priced = api.post(
        url, json={"contract_change": "1000", "budget_change": "800"}, headers=qs.headers
    ).json()

    # Small and without time impact, but raised by the PM: the client approves, not the PM.
    assert (priced["status"], priced["approver"], priced["needs_client"]) == (
        "awaiting_client",
        "client",
        False,
    )
    seen = api.get(f"/api/v1/client/variations/{variation['id']}", headers=client_user.headers).json()
    assert "raised by the project manager" in seen["reason_for_client"]
    pm_decision = api.post(
        f"/api/v1/variations/{variation['id']}/decision", json={"decision": "approve"}, headers=pm.headers
    )
    assert pm_decision.status_code == 403  # the PM raised it


def test_the_client_queries_and_a_revision_goes_back_to_the_client(
    api: TestClient, db: Session, boq: Boq, qs: Who, pm: Who, client_user: Who
) -> None:
    variation = raise_variation(api, boq, qs, contract_change="500000", budget_change="400000",
                                comment="Priced from the subcontractor's quote")  # fmt: skip
    url = f"/api/v1/variations/{variation['id']}/client-decision"

    assert api.post(url, json={"decision": "query"}, headers=client_user.headers).status_code == 422
    queried = api.post(
        url, json={"decision": "query", "comment": "Why so much?"}, headers=client_user.headers
    ).json()
    assert queried["status"] == "queried"
    assert len(notes_of(db, qs, "variation_queried")) == 1
    assert len(notes_of(db, pm, "variation_queried")) == 1
    revised = api.post(
        f"/api/v1/variations/{variation['id']}/revision",
        json=variation_body(boq, contract_change="60000", budget_change="45000", comment="Quote revised"),
        headers=qs.headers,
    ).json()

    # Now under the limit, but the client has seen it: it goes back to them, not to the PM.
    assert (revised["status"], revised["contract_change"]) == ("awaiting_client", "60000.00")
    client_view = api.get(f"/api/v1/client/variations/{variation['id']}", headers=client_user.headers).json()
    assert "budget_change" not in client_view
    comments = [e["comment"] for e in client_view["events"]]
    assert "Why so much?" in comments
    assert "Priced from the subcontractor's quote" not in comments
    assert "Quote revised" not in comments
    assert {e["actor"] for e in client_view["events"] if e["comment"] is None} == {"Contractor"}


def test_the_client_sees_only_their_sites(
    api: TestClient, boq: Boq, qs: Who, team: Callable[..., Who], make_site: Callable[..., Site]
) -> None:
    variation = raise_variation(api, boq, qs, contract_change="500000", budget_change="0")
    other_client = team(Role.CLIENT, sites=[make_site("KDY-01")])

    assert api.get("/api/v1/client/variations", headers=other_client.headers).json() == []
    url = f"/api/v1/variations/{variation['id']}/client-decision"
    assert api.post(url, json={"decision": "approve"}, headers=other_client.headers).status_code == 404
    assert (
        api.get(f"/api/v1/client/variations/{variation['id']}", headers=other_client.headers).status_code
        == 404
    )


def test_the_pm_cannot_decide_what_waits_for_the_client(api: TestClient, boq: Boq, qs: Who, pm: Who) -> None:
    variation = raise_variation(api, boq, qs, contract_change="500000", budget_change="0")

    response = api.post(
        f"/api/v1/variations/{variation['id']}/decision", json={"decision": "approve"}, headers=pm.headers
    )

    assert response.status_code == 409


@pytest.mark.parametrize("decision", ["query", "reject"])
def test_the_pm_queries_or_rejects_with_a_reason(
    api: TestClient, boq: Boq, qs: Who, pm: Who, decision: str
) -> None:
    variation = raise_variation(api, boq, qs, contract_change="1000", budget_change="0")
    url = f"/api/v1/variations/{variation['id']}/decision"

    assert api.post(url, json={"decision": decision}, headers=pm.headers).status_code == 422
    decided = api.post(url, json={"decision": decision, "comment": "Not in scope"}, headers=pm.headers).json()

    assert decided["status"] == {"query": "queried", "reject": "rejected"}[decision]


def test_only_the_raiser_withdraws(api: TestClient, db: Session, boq: Boq, qs: Who, pm: Who) -> None:
    variation = raise_variation(api, boq, qs)
    url = f"/api/v1/variations/{variation['id']}/withdraw"

    assert api.post(url, json={}, headers=pm.headers).status_code == 403
    assert api.post(url, json={"comment": "Not needed"}, headers=qs.headers).json()["status"] == "withdrawn"
    assert api.post(url, json={}, headers=qs.headers).status_code == 409
    assert audits(db, "variation.withdrawn")[0].details["from"] == "awaiting_pricing"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"time_impact_days": 5}, "needs the programme task"),
        ({"boq_item_id": None}, "Extra quantity needs its BOQ item"),
        ({"section_id": "00000000-0000-0000-0000-000000000001"}, "Choose a section"),
        ({"contract_change": "1000"}, "Price both"),
        ({"contract_change": "-10000000", "budget_change": "0"}, "contract value to zero"),
        ({"contract_change": "0", "budget_change": "-4400000.01"}, "budget below zero"),
    ],
)
def test_a_variation_is_validated(
    api: TestClient, boq: Boq, qs: Who, overrides: dict[str, object], message: str
) -> None:
    response = api.post(
        f"/api/v1/projects/{boq.project.id}/variations",
        json=variation_body(boq, **overrides),
        headers=qs.headers,
    )

    assert response.status_code == 422
    assert message in response.json()["error"]["message"]


def test_variations_are_not_for_engineers_or_procurement(
    api: TestClient, boq: Boq, qs: Who, se: Who, buyer: Who
) -> None:
    variation = raise_variation(api, boq, qs)
    for who in (se, buyer):
        assert (
            api.get(f"/api/v1/projects/{boq.project.id}/variations", headers=who.headers).status_code == 403
        )
        assert api.get(f"/api/v1/variations/{variation['id']}", headers=who.headers).status_code == 403


def test_the_variation_list_totals_approved_changes(
    api: TestClient, boq: Boq, qs: Who, pm: Who, task: Task
) -> None:
    first = raise_variation(api, boq, qs, contract_change="1000", budget_change="0")
    api.post(f"/api/v1/variations/{first['id']}/decision", json={"decision": "approve"}, headers=pm.headers)
    raise_variation(
        api, boq, qs, contract_change="500000", budget_change="0", time_impact_days=3, task_id=str(task.id)
    )

    listing = api.get(f"/api/v1/projects/{boq.project.id}/variations", headers=pm.headers).json()

    assert (listing["approved_contract_change"], listing["approved_time_impact_days"]) == ("1000.00", 0)
    assert [v["status"] for v in listing["variations"]] == ["awaiting_client", "approved"]


# --- The BR-09 limit: Company Admin only -----------------------------------------------------------


def test_only_the_admin_changes_the_limit_and_it_is_audited(
    api: TestClient, db: Session, boq: Boq, admin: Who, pm: Who, qs: Who
) -> None:
    url = f"/api/v1/admin/projects/{boq.project.id}/variation-limit"
    body = {"variation_limit": "250000", "reason": "Contract clause 13.4 allows LKR 250,000"}

    for who in (pm, qs):
        assert api.put(url, json=body, headers=who.headers).status_code == 403
    assert (
        api.put(url, json={"variation_limit": "250000"}, headers=admin.headers).status_code == 422
    )  # no reason
    changed = api.put(url, json=body, headers=admin.headers).json()

    assert changed["variation_limit"] == "250000.00"
    [entry] = audits(db, "project.variation_limit_changed")
    assert entry.details == {
        "project": "HR-1",
        "from": "100000.00",
        "to": "250000.00",
        "reason": "Contract clause 13.4 allows LKR 250,000",
    }
    assert api.put(url, json=body, headers=admin.headers).status_code == 422  # unchanged
    listed = api.get("/api/v1/admin/variation-limits", headers=admin.headers).json()
    assert [(p["code"], p["variation_limit"]) for p in listed] == [("HR-1", "250000.00")]


def test_a_new_limit_applies_to_the_next_pricing_only(api: TestClient, boq: Boq, admin: Who, qs: Who) -> None:
    routed = raise_variation(api, boq, qs, contract_change="200000", budget_change="0")
    api.put(
        f"/api/v1/admin/projects/{boq.project.id}/variation-limit",
        json={"variation_limit": "250000", "reason": "Agreed with the client"},
        headers=admin.headers,
    )
    later = raise_variation(api, boq, qs, contract_change="200000", budget_change="0")

    assert (routed["status"], later["status"]) == ("awaiting_client", "awaiting_pm")
    refreshed = api.get(f"/api/v1/variations/{routed['id']}", headers=qs.headers).json()
    assert (refreshed["limit_applied"], refreshed["limit"]) == ("100000.00", "250000.00")


def test_new_projects_get_one_percent(db: Session, boq: Boq) -> None:
    assert db.get(Project, boq.project.id).variation_limit == D("100000.00")  # type: ignore[union-attr]


# --- Forecast final cost and variance alerts --------------------------------------------------------


def test_budget_shows_the_forecast_and_alerts_an_overrun_once(
    api: TestClient, db: Session, boq: Boq, se: Who, qs: Who, pm: Who
) -> None:
    """500 bags budgeted at LKR 2,000 (1,000,000) bought at 2,400 (1,200,000): trend 1.2.

    Forecast = 1,200,000 + (4,400,000 - 1,000,000) x 1.2 = 5,280,000: 20% over, so PM and QS are alerted.
    """
    request = raise_request(api, boq, se, quantity="500")
    decided = decide(api, request["id"], qs, "approve", unit_price="2400")
    if decided.json()["status"] == "pm_approval":
        decide(api, request["id"], pm, "approve")

    budget = api.get(f"/api/v1/projects/{boq.project.id}/budget", headers=pm.headers).json()
    [line] = budget["lines"]

    assert (line["committed"], line["forecast_final"], line["variance"]) == (
        "1200000.00",
        "5280000.00",
        "-880000.00",
    )
    assert (line["trend"], line["variance_pct"], line["over_alert_line"]) == ("1.200", "-20.0", True)
    assert line["basis_pct"] == "22.7"  # 1,000,000 of 4,400,000
    assert line["over_budget_since"] == clock.site_today().isoformat()
    assert budget["totals"]["forecast_final"] == "5280000.00"
    for who in (pm, qs):
        [alert] = notes_of(db, who, "cost_variance")
        assert "20.0% over" in alert.body
    second = raise_request(api, boq, se, quantity="10")
    decide(api, second["id"], qs, "approve", unit_price="2400")
    assert len(notes_of(db, pm, "cost_variance")) == 1  # still over: no second alert


def test_coming_back_under_clears_the_alert(db: Session, boq: Boq, pm: Who) -> None:

    line = db.get(BudgetLine, boq.line.id)
    assert line is not None
    line.over_budget_since = clock.site_today()
    db.commit()

    assert cost_service.check_variance(db, boq.project) == []
    db.commit()

    db.refresh(line)
    assert line.over_budget_since is None
    assert notes_of(db, pm, "cost_variance") == []


def test_the_daily_check_covers_active_projects(db: Session, boq: Boq) -> None:

    assert cost_service.check_all(db) == 0


# --- Edges ----------------------------------------------------------------------------------------------


def test_unknown_and_out_of_scope_records_answer_404(
    api: TestClient, boq: Boq, qs: Who, team: Callable[..., Who], make_site: Callable[..., Site], admin: Who
) -> None:
    variation = raise_variation(api, boq, qs)
    claim = make_claim(api, boq, qs, "10")
    elsewhere = team(Role.QUANTITY_SURVEYOR, sites=[make_site("KDY-01")])
    missing = "00000000-0000-0000-0000-000000000001"

    assert api.get(f"/api/v1/variations/{missing}", headers=qs.headers).status_code == 404
    assert api.get(f"/api/v1/variations/{variation['id']}", headers=elsewhere.headers).status_code == 404
    assert api.get(f"/api/v1/claims/{missing}", headers=qs.headers).status_code == 404
    assert api.get(f"/api/v1/claims/{claim['id']}", headers=elsewhere.headers).status_code == 404
    body = {"variation_limit": "1.00", "reason": "Not a project"}
    assert (
        api.put(
            f"/api/v1/admin/projects/{missing}/variation-limit", json=body, headers=admin.headers
        ).status_code
        == 404
    )


def test_the_item_and_task_must_belong_to_the_variation(
    api: TestClient, db: Session, boq: Boq, qs: Who, task: Task
) -> None:
    other = Project(
        code="OTHER", name="Other", site_id=boq.project.site_id, client_name="C", project_type="residential",
        status="active", contract_value=D("1000000"), start_date=date(2026, 1, 1),
        planned_end=date(2026, 12, 31),
    )  # fmt: skip
    db.add(other)
    db.flush()
    foreign_task = Task(
        project_id=other.id, name="Elsewhere", planned_start=date(2026, 1, 5), planned_end=date(2026, 2, 5),
        weight=D(10), position=1,
    )  # fmt: skip
    db.add(foreign_task)
    db.commit()
    url = f"/api/v1/projects/{boq.project.id}/variations"

    wrong_task = api.post(
        url, json=variation_body(boq, task_id=str(foreign_task.id), time_impact_days=2), headers=qs.headers
    )
    wrong_item = api.post(url, json=variation_body(boq, boq_item_id=str(boq.project.id)), headers=qs.headers)

    assert "task from this project" in wrong_task.json()["error"]["message"]
    assert "item must be in the chosen section" in wrong_item.json()["error"]["message"]


def test_pricing_and_revising_happen_in_their_states(api: TestClient, boq: Boq, qs: Who, pm: Who) -> None:
    priced = raise_variation(api, boq, qs, contract_change="1000", budget_change="0")
    queried_by_pm = raise_variation(api, boq, qs, contract_change="1000", budget_change="0")
    api.post(f"/api/v1/variations/{queried_by_pm['id']}/decision",
             json={"decision": "query", "comment": "Which drawing?"}, headers=pm.headers)  # fmt: skip

    again = api.post(
        f"/api/v1/variations/{priced['id']}/price",
        json={"contract_change": "1", "budget_change": "0"},
        headers=qs.headers,
    )
    not_queried = api.post(
        f"/api/v1/variations/{priced['id']}/revision", json=variation_body(boq), headers=qs.headers
    )
    by_pm = api.post(
        f"/api/v1/variations/{queried_by_pm['id']}/revision", json=variation_body(boq), headers=pm.headers
    )
    by_raiser = api.post(
        f"/api/v1/variations/{queried_by_pm['id']}/revision", json=variation_body(boq), headers=qs.headers
    )

    assert (again.status_code, not_queried.status_code, by_pm.status_code) == (409, 409, 403)
    assert by_raiser.json()["status"] == "awaiting_pricing"  # revised without a price: priced again


def test_approval_refuses_a_budget_that_changed_since_pricing(
    api: TestClient, db: Session, boq: Boq, qs: Who, pm: Who
) -> None:
    variation = raise_variation(api, boq, qs, contract_change="1000", budget_change="-4000000")
    line = db.get(BudgetLine, boq.line.id)
    assert line is not None
    line.budget_amount = D("1000000.00")  # the QS has since cut the section's budget
    db.commit()

    response = api.post(
        f"/api/v1/variations/{variation['id']}/decision", json={"decision": "approve"}, headers=pm.headers
    )

    assert response.status_code == 409
    assert "price it again" in response.json()["error"]["message"]
    db.expire_all()
    assert db.get(Project, boq.project.id).contract_value == D("10000000.00")  # type: ignore[union-attr]


def test_variance_is_not_checked_on_closed_projects_and_never_breaks_the_caller(
    db: Session, boq: Boq, monkeypatch: pytest.MonkeyPatch
) -> None:

    project = db.get(Project, boq.project.id)
    assert project is not None
    project.status = "completed"
    db.commit()
    assert cost_service.check_variance(db, project) == []

    project.status = "active"
    db.commit()

    def boom(*_: object) -> None:
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(cost_service, "forecasts", boom)
    cost_service.check_after_change(db, project)  # logged, not raised
    assert cost_service.check_all(db) == 0


# --- Cost & claims overview -------------------------------------------------------------------------


def test_the_overview_shows_each_project_and_what_waits_for_whom(
    api: TestClient, boq: Boq, qs: Who, pm: Who, client_user: Who
) -> None:
    claim = make_claim(api, boq, qs, "40")
    for_qs = raise_variation(api, boq, pm)  # to price
    for_pm = raise_variation(api, boq, qs, contract_change="1000", budget_change="0")

    pm_view = api.get("/api/v1/cost/overview", headers=pm.headers).json()
    qs_view = api.get("/api/v1/cost/overview", headers=qs.headers).json()

    [row] = pm_view["projects"]
    assert (row["code"], row["budget"], row["forecast_final"], row["variance"]) == (
        "HR-1",
        "4400000.00",
        "4400000.00",
        "0.00",
    )
    assert (row["open_claim"], row["variations_open"], row["claimed_to_date"]) == (claim["number"], 2, "0.00")
    assert {(w["kind"], w["id"]) for w in pm_view["waiting_for_you"]} == {
        ("claim", claim["id"]),
        ("variation", for_pm["id"]),
    }
    assert [(w["kind"], w["id"]) for w in qs_view["waiting_for_you"]] == [("variation", for_qs["id"])]
    assert api.get("/api/v1/cost/overview", headers=client_user.headers).status_code == 403


def test_approved_variations_count_in_the_project_totals_for_rate_readers_only(
    api: TestClient, boq: Boq, qs: Who, pm: Who, se: Who
) -> None:
    """Margins compare BOQ + approved variations with the budget, so both sides include the change."""
    variation = raise_variation(api, boq, qs, contract_change="90000", budget_change="72000")
    api.post(
        f"/api/v1/variations/{variation['id']}/decision", json={"decision": "approve"}, headers=pm.headers
    )

    detail = api.get(f"/api/v1/projects/{boq.project.id}", headers=pm.headers).json()
    listed = api.get("/api/v1/projects", headers=pm.headers).json()
    board = api.get(f"/api/v1/projects/{boq.project.id}/boq", headers=pm.headers).json()
    engineer = api.get(f"/api/v1/projects/{boq.project.id}", headers=se.headers).json()

    assert (detail["variations_total"], detail["sections"][0]["variation_amount"]) == ("90000.00", "90000.00")
    assert detail["budget_total"] == "4472000.00"
    assert next(p for p in listed if p["code"] == "HR-1")["variations_total"] == "90000.00"
    assert board["variations_total"] == "90000.00"
    assert "variations_total" not in engineer
    assert "variation_amount" not in engineer["sections"][0]


def test_a_variation_locks_the_contract_even_in_planning(
    api: TestClient, db: Session, boq: Boq, qs: Who, pm: Who
) -> None:
    project = db.get(Project, boq.project.id)
    assert project is not None
    project.status = "planning"
    db.commit()
    assert (
        api.get(f"/api/v1/projects/{boq.project.id}", headers=pm.headers).json()["contract_locked"] is False
    )

    raise_variation(api, boq, qs)

    assert api.get(f"/api/v1/projects/{boq.project.id}", headers=pm.headers).json()["contract_locked"] is True
    refused = api.patch(
        f"/api/v1/projects/{boq.project.id}", json={"contract_value": "1.00"}, headers=pm.headers
    )
    assert refused.json()["error"]["code"] == "contract_locked"


def test_a_section_still_over_the_next_day_does_not_alert_again(
    api: TestClient, db: Session, boq: Boq, se: Who, qs: Who, pm: Who
) -> None:
    """The alert is on entry: the notification de-duplication alone would allow one a day."""

    request = raise_request(api, boq, se, quantity="500")
    decided = decide(api, request["id"], qs, "approve", unit_price="2400")
    if decided.json()["status"] == "pm_approval":
        decide(api, request["id"], pm, "approve")
    assert len(notes_of(db, pm, "cost_variance")) == 1

    project = db.get(Project, boq.project.id)
    assert project is not None
    tomorrow = clock.site_today() + timedelta(days=1)
    assert cost_service.check_variance(db, project, on=tomorrow) == []
    db.commit()

    assert len(notes_of(db, pm, "cost_variance")) == 1
    assert db.get(BudgetLine, boq.line.id).over_budget_since == clock.site_today()  # type: ignore[union-attr]
