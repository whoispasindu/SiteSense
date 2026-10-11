"""Phase 8 rules without a database: forecast final cost, BR-08 claims, BR-09 variations."""

import uuid
from decimal import Decimal

import pytest

from app.rules import claims, cost, variations
from app.rules.variations import VariationStatus

D = Decimal

# --- Forecast final cost ----------------------------------------------------------------------------


def test_nothing_committed_forecasts_the_budget() -> None:
    f = cost.forecast_final_cost(budget=D("1000000"), committed=D(0), committed_budget_value=D(0))

    assert (f.final_cost, f.variance, f.trend, f.basis_share) == (D("1000000.00"), D(0), None, D(0))
    assert not f.over_alert_line


def test_the_trend_so_far_carries_over_the_remaining_budget() -> None:
    """100,000 of budgeted work bought for 110,000 (trend 1.1): the other 900,000 forecasts 990,000."""
    f = cost.forecast_final_cost(
        budget=D("1000000"), committed=D("110000"), committed_budget_value=D("100000")
    )

    assert f.trend == D("1.1")
    assert f.final_cost == D("1100000.00")
    assert f.variance == D("-100000.00")
    assert f.variance_share == D("-0.1")
    assert f.basis_share == D("0.1")
    assert f.over_alert_line


def test_work_bought_under_budget_forecasts_a_saving() -> None:
    f = cost.forecast_final_cost(
        budget=D("500000"), committed=D("190000"), committed_budget_value=D("200000")
    )

    assert f.final_cost == D("475000.00")
    assert f.variance == D("25000.00")
    assert not f.over_alert_line


@pytest.mark.parametrize(
    ("final", "alerts"),
    [("1050000.00", False), ("1050000.01", True)],  # the line is exactly 5% over
)
def test_the_alert_line_is_five_percent_over_budget(final: str, alerts: bool) -> None:
    f = cost.Forecast(budget=D("1000000"), final_cost=D(final), trend=D(1), basis_share=D(1))

    assert f.over_alert_line is alerts


def test_committed_beyond_the_budget_counts_in_full() -> None:
    """Committed quantities already past the budget leave no remaining budget, not a negative one."""
    f = cost.forecast_final_cost(
        budget=D("100000"), committed=D("130000"), committed_budget_value=D("120000")
    )

    assert f.final_cost == D("130000.00")
    assert f.basis_share == D(1)


def test_a_zero_budget_with_spending_is_over() -> None:
    f = cost.forecast_final_cost(budget=D(0), committed=D("5000"), committed_budget_value=D(0))

    assert f.final_cost == D("5000.00")
    assert f.variance_share is None
    assert f.over_alert_line


# --- BR-08: progress claims -------------------------------------------------------------------------


def section(value: str, pct: str, previous: str = "0") -> claims.SectionProgress:
    return claims.SectionProgress(uuid.uuid4(), D(value), D(pct), D(previous))


def test_br08_first_claim_holds_five_percent_retention() -> None:
    """30% certified of a 10 M contract: 3,000,000 certified, 150,000 retained, 2,850,000 claimed."""
    figures = claims.calculate(
        contract_value=D("10000000"), sections=[section("10000000", "30")], previous_claims=D(0)
    )

    assert figures.certified_value == D("3000000.00")
    assert figures.retention == D("150000.00")
    assert figures.amount == D("2850000.00")
    assert figures.amount == figures.limit


def test_br08_previous_claims_are_deducted() -> None:
    """Now 50%: 5,000,000 certified, 250,000 retained, less the 2,850,000 already claimed."""
    figures = claims.calculate(
        contract_value=D("10000000"), sections=[section("10000000", "50", "30")], previous_claims=D("2850000")
    )

    assert figures.amount == D("1900000.00")
    assert figures.retention == D("250000.00")


def test_br08_sections_are_weighted_by_their_contract_value() -> None:
    """Substructure (2 M) 100% and superstructure (6 M) 25%: (2 + 1.5) / 8 = 43.75%."""
    figures = claims.calculate(
        contract_value=D("8000000"),
        sections=[section("2000000", "100"), section("6000000", "25")],
        previous_claims=D(0),
    )

    assert figures.certified_pct == D("43.75")
    assert figures.certified_value == D("3500000.00")


def test_br08_uses_the_contract_value_when_the_boq_total_differs() -> None:
    """BR-08 is progress times *contract value*: the BOQ only gives the weights."""
    figures = claims.calculate(
        contract_value=D("11000000"), sections=[section("10000000", "10")], previous_claims=D(0)
    )

    assert figures.certified_value == D("1100000.00")


def test_br08_rounding_never_lets_a_claim_exceed_the_limit() -> None:
    for value in ("1234567.89", "999.99", "0.10", "7777777.77"):
        for pct in ("0.01", "33.33", "66.67", "99.99"):
            figures = claims.calculate(
                contract_value=D(value), sections=[section(value, pct)], previous_claims=D(0)
            )
            assert figures.amount <= figures.limit
            assert figures.amount + figures.retention + figures.previous_claims == figures.certified_value


@pytest.mark.parametrize(
    ("pct", "previous", "message"),
    [
        ("-1", "0", "between 0% and 100%"),
        ("100.01", "0", "between 0% and 100%"),
        ("20", "30", "below the last approved claim"),
    ],
)
def test_br08_certified_progress_is_checked(pct: str, previous: str, message: str) -> None:
    sections = [section("1000000", pct, previous)]
    figures = claims.calculate(contract_value=D("1000000"), sections=sections, previous_claims=D(0))

    [problem] = claims.check(sections, figures)

    assert problem.blocks
    assert message in problem.message


def test_br08_a_claim_with_nothing_new_is_refused() -> None:
    sections = [section("1000000", "30", "30")]
    figures = claims.calculate(contract_value=D("1000000"), sections=sections, previous_claims=D("285000"))

    [problem] = claims.check(sections, figures)

    assert figures.amount == D(0)
    assert "Nothing to claim" in problem.message


def test_br08_a_valid_claim_has_no_problems() -> None:
    sections = [section("1000000", "40", "30")]
    figures = claims.calculate(contract_value=D("1000000"), sections=sections, previous_claims=D("285000"))

    assert claims.check(sections, figures) == []
    assert figures.amount == D("95000.00")


# --- BR-09: variations -------------------------------------------------------------------------------


def test_br09_default_limit_is_one_percent_of_the_contract_value() -> None:
    assert variations.default_limit(D("1110000000")) == D("11100000.00")


def test_br09_a_revision_goes_back_to_the_client_who_saw_it() -> None:
    assert (
        variations.route(
            contract_change=D(1), time_impact_days=0, limit=D("1000000"), raised_by="qs", seen_by_client=True
        )
        == "client"
    )


@pytest.mark.parametrize(
    ("change", "days", "raised_by", "approver"),
    [
        ("100000", 0, "qs", "pm"),  # small, no time: the PM
        ("1000000", 0, "qs", "pm"),  # exactly the limit is not above it
        ("1000000.01", 0, "qs", "client"),  # above the limit
        ("-1000000.01", 0, "qs", "client"),  # a large omission too
        ("0", 1, "qs", "client"),  # any time impact
        ("100000", 0, "pm", "client"),  # a PM never approves their own
    ],
)
def test_br09_routing(change: str, days: int, raised_by: variations.RaisedBy, approver: str) -> None:
    assert (
        variations.route(
            contract_change=D(change), time_impact_days=days, limit=D("1000000"), raised_by=raised_by
        )
        == approver
    )


@pytest.mark.parametrize(
    ("status", "decision", "by", "expected"),
    [
        ("awaiting_pm", "approve", "pm", VariationStatus.APPROVED),
        ("awaiting_pm", "query", "pm", VariationStatus.QUERIED),
        ("awaiting_pm", "reject", "pm", VariationStatus.REJECTED),
        ("awaiting_client", "approve", "client", VariationStatus.APPROVED),
        ("awaiting_client", "query", "client", VariationStatus.QUERIED),
    ],
)
def test_variation_decisions(
    status: str, decision: variations.Decision, by: variations.Approver, expected: VariationStatus
) -> None:
    assert variations.next_status(status=status, decision=decision, by=by) == expected


@pytest.mark.parametrize(
    ("status", "decision", "by"),
    [
        ("awaiting_client", "approve", "pm"),  # the PM cannot approve what waits for the client
        ("awaiting_pm", "approve", "client"),
        ("awaiting_pricing", "approve", "pm"),  # not priced yet
        ("approved", "approve", "client"),
        ("awaiting_client", "reject", "client"),  # the client approves or queries
    ],
)
def test_impossible_variation_decisions(
    status: str, decision: variations.Decision, by: variations.Approver
) -> None:
    with pytest.raises(variations.TransitionError):
        variations.next_status(status=status, decision=decision, by=by)


def test_a_variation_cannot_take_a_budget_below_zero() -> None:
    assert variations.check_budget_change(line_budget=D("1000"), budget_change=D("-1000")) is None
    assert variations.check_budget_change(line_budget=D("1000"), budget_change=D("-1000.01")) is not None
