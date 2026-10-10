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


# --- BR-01: unit price against the item's budgeted rate -------------------------------------------


@pytest.mark.parametrize(
    ("price", "severity"),
    [("90", "pass"), ("100", "pass"), ("105", "pass"), ("105.01", "warn"), ("106", "warn")],
)
def test_br01_fires_only_above_five_percent_over_the_budgeted_rate(price: str, severity: str) -> None:
    """TC-02: 6% over the budgeted rate needs the project manager."""
    result = rules.check_price(unit_price=D(price), budget_rate=D(100))

    assert result.rule == "BR-01"
    assert result.severity == severity
    assert result.facts["budget_rate"] == "100.00"


def test_br01_messages_are_in_words() -> None:
    assert rules.check_price(unit_price=D(103), budget_rate=D(100)).message == (
        "3.0% above the budgeted rate: within the 5% limit."
    )
    assert rules.check_price(unit_price=D(95), budget_rate=D(100)).message == "At or below the budgeted rate."
    assert "6.0% above the budgeted rate" in rules.check_price(unit_price=D(106), budget_rate=D(100)).message
    assert rules.check_price(unit_price=D(10), budget_rate=D(0)).severity == "warn"


def test_br01_ignores_the_section_budget() -> None:
    """A price on budget passes BR-01 however full the section is: that is BR-13's job."""
    assert rules.check_price(unit_price=D(100), budget_rate=D(100)).severity == "pass"


# --- BR-13: the section's committed cost against its budget line ----------------------------------


@pytest.mark.parametrize(
    ("committed", "amount", "severity"),
    [
        ("0", "1000", "pass"),
        ("99000", "1000", "pass"),  # exactly the budget line: still fine
        ("99000", "1000.01", "warn"),  # one cent over
        ("150000", "1", "warn"),  # already over before this request
    ],
)
def test_br13_fires_when_committed_cost_plus_the_request_exceeds_the_budget_line(
    committed: str, amount: str, severity: str
) -> None:
    result = rules.check_section_budget(
        line_budget=D(100000), line_committed=D(committed), request_amount=D(amount)
    )

    assert result.rule == "BR-13"
    assert result.severity == severity


def test_br13_has_no_tolerance_and_says_by_how_much() -> None:
    result = rules.check_section_budget(
        line_budget=D(100000), line_committed=D(99000), request_amount=D(2000)
    )

    assert result.facts["line_after_request"] == "101000.00"
    assert result.facts["line_over"] == "1000.00"
    assert "LKR 101,000.00 against a budget line of LKR 100,000.00" in result.message


# --- Routing: who approves --------------------------------------------------------------------------


def route(unit_price: str, *, budget_rate: str = "100", line_budget: str = "100000", committed: str = "0"):  # type: ignore[no-untyped-def]
    return rules.route_approval(
        unit_price=D(unit_price),
        budget_rate=D(budget_rate),
        request_amount=D(unit_price) * 10,
        line_budget=D(line_budget),
        line_committed=D(committed),
    )


def test_qs_approves_when_neither_rule_fires() -> None:
    level, results, fired = route("104")

    assert level == "qs"
    assert [r.rule for r in results] == ["BR-01", "BR-13"]
    assert fired == []


def test_br01_alone_sends_to_the_pm() -> None:
    level, _, fired = route("106")

    assert (level, fired) == ("pm", ["BR-01"])


def test_br13_alone_sends_to_the_pm() -> None:
    level, _, fired = route("100", committed="99500")  # price on budget, section full

    assert (level, fired) == ("pm", ["BR-13"])


def test_both_rules_can_fire() -> None:
    level, _, fired = route("110", committed="99500")

    assert (level, fired) == ("pm", ["BR-01", "BR-13"])


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
