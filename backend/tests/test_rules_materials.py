"""The materials rules as pure functions: every boundary, without a database."""

from decimal import Decimal

import pytest

from app.rules import materials as rules

D = Decimal


# --- BR-02: quantity against the BOQ allowance ---------------------------------------------------


@pytest.mark.parametrize(
    ("already", "requested", "severity"),
    [
        (D(0), D(100), "pass"),  # exactly the BOQ quantity
        (D(60), D(40), "pass"),
        (D(60), D(43), "warn"),  # 103: exactly the 3% tolerance
        (D(0), D("103.001"), "block"),  # just over
        (D(100), D(10), "block"),
    ],
)
def test_quantity_tolerance_is_three_percent(already: Decimal, requested: Decimal, severity: str) -> None:
    result = rules.check_quantity(boq_quantity=D(100), already_requested=already, requested=requested)

    assert result.rule == "BR-02"
    assert result.severity == severity
    assert result.blocks is (severity == "block")


def test_messages_use_readable_quantities() -> None:
    result = rules.check_quantity(boq_quantity=D("1650.000"), already_requested=D(0), requested=D("400.000"))

    assert result.message == "400 of 1,650 requested so far for this item, including this one."
    assert result.facts["boq_quantity"] == "1650.000"
    half = rules.check_quantity(boq_quantity=D("10.000"), already_requested=D("0"), requested=D("2.500"))
    assert half.message.startswith("2.5 of 10 ")


def test_an_approved_variation_raises_the_allowance() -> None:
    blocked = rules.check_quantity(boq_quantity=D(100), already_requested=D(0), requested=D(120))
    allowed = rules.check_quantity(
        boq_quantity=D(100), already_requested=D(0), requested=D(120), approved_variation=D(20)
    )

    assert blocked.blocks
    assert "20.0% over" in blocked.message
    assert not allowed.blocks


# --- BR-01: routing --------------------------------------------------------------------------------


def route(unit_price: str, *, budget_rate: str = "100", line_budget: str = "100000", line_used: str = "0"):  # type: ignore[no-untyped-def]
    return rules.route_approval(
        unit_price=D(unit_price),
        budget_rate=D(budget_rate),
        request_amount=D(unit_price) * 10,
        line_budget=D(line_budget),
        line_used=D(line_used),
    )


@pytest.mark.parametrize(
    ("price", "level"),
    [("90", "qs"), ("100", "qs"), ("105", "qs"), ("105.01", "pm"), ("106", "pm")],
)
def test_qs_approves_up_to_five_percent_over_the_budgeted_rate(price: str, level: str) -> None:
    """TC-02: a request 6% over goes to the project manager."""
    chosen, result = route(price)

    assert chosen == level
    assert result.rule == "BR-01"
    assert result.facts["budget_rate"] == "100.00"


def test_a_budget_line_that_would_end_over_five_percent_needs_the_pm() -> None:
    # Price on budget, but the line is nearly used up: 100,000 budget, 104,500 already used, +1,000.
    level, result = route("100", line_used="104500")

    assert level == "pm"
    assert "budget line would end 5.5% over" in result.message


def test_within_tolerance_is_said_in_words() -> None:
    assert route("103")[1].message == "Within the 5% tolerance: the QS can approve."
    assert route("95")[1].message == "Within budget: the QS can approve."


def test_no_budget_means_the_pm_decides() -> None:
    assert route("10", budget_rate="0")[0] == "pm"
    assert route("10", line_budget="0")[0] == "pm"


def test_item_budget_rate_is_its_share_of_the_line() -> None:
    # Section worth 200,000 at contract rates with a 160,000 cost budget: 80% of the contract rate.
    assert rules.item_budget_rate(item_rate=D(1000), section_amount=D(200000), line_budget=D(160000)) == D(
        800
    )
    assert rules.item_budget_rate(item_rate=D(1000), section_amount=D(0), line_budget=D(1)) == D(0)


# --- BR-04 and BR-05 -------------------------------------------------------------------------------


def test_requester_cannot_decide_their_own_request() -> None:
    assert rules.check_not_own_request(actor_id="a", requester_id="a").blocks
    assert not rules.check_not_own_request(actor_id="b", requester_id="a").blocks


@pytest.mark.parametrize(
    "status",
    ["requested", "pm_approval", "change_requested", "rejected", "cancelled", "ordered", "delivered"],
)
def test_only_approved_requests_can_be_ordered(status: str) -> None:
    assert rules.check_can_order(status=status).blocks
    assert not rules.check_can_order(status="approved").blocks


# --- State machine ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "decision", "stage", "level", "expected"),
    [
        ("requested", "approve", "qs", "qs", "approved"),
        ("requested", "approve", "qs", "pm", "pm_approval"),
        ("requested", "reject", "qs", "qs", "rejected"),
        ("requested", "request_change", "qs", "qs", "change_requested"),
        ("pm_approval", "approve", "pm", "pm", "approved"),
        ("pm_approval", "reject", "pm", "pm", "rejected"),
        ("pm_approval", "request_change", "pm", "pm", "change_requested"),
        ("change_requested", "resubmit", "requester", "qs", "requested"),
        ("requested", "cancel", "requester", "qs", "cancelled"),
        ("pm_approval", "cancel", "requester", "pm", "cancelled"),
        ("change_requested", "cancel", "requester", "qs", "cancelled"),
    ],
)
def test_allowed_transitions(status: str, decision: str, stage: str, level: str, expected: str) -> None:
    assert rules.next_status(status=status, decision=decision, stage=stage, approval_level=level) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "decision", "stage"),
    [
        ("approved", "approve", "qs"),  # already approved
        ("approved", "cancel", "requester"),  # too late to cancel
        ("ordered", "reject", "pm"),
        ("delivered", "request_change", "qs"),
        ("rejected", "approve", "pm"),
        ("cancelled", "resubmit", "requester"),
        ("requested", "approve", "pm"),  # the PM cannot skip the QS check
        ("pm_approval", "approve", "qs"),  # the QS cannot approve above the limit
        ("requested", "resubmit", "requester"),
    ],
)
def test_invalid_transitions_are_refused(status: str, decision: str, stage: str) -> None:
    with pytest.raises(rules.TransitionError):
        rules.next_status(status=status, decision=decision, stage=stage, approval_level="qs")  # type: ignore[arg-type]


def test_who_acts_next() -> None:
    assert rules.stage_for("requested") == "qs"
    assert rules.stage_for("pm_approval") == "pm"
    assert rules.stage_for("change_requested") == "requester"
    assert rules.stage_for("approved") is None
