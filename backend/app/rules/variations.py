"""Variation orders: BR-09 routing and the approval states (Phase 8).

A PM or QS raises a variation; the QS prices every variation (the change to the contract value and
to the section's cost budget) before anyone approves it. Then:

- BR-09: any time impact, or a contract change larger than the project's variation limit (either
  way: additions and omissions), needs the client's approval;
- otherwise a variation raised by the QS goes to a project manager;
- a variation raised by a project manager goes to the client, so nobody approves their own.
- once a variation has been with the client, a revision of it goes back to the client.

The limit is set per project (1% of the contract value when the project is created) and only the
Company Admin can change it.

Pure functions over plain values; tested in ``tests/test_rules_variations.py``.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from app.rules.materials import ZERO, money

DEFAULT_LIMIT_SHARE = Decimal("0.01")  # BR-09 default: 1% of the contract value


class VariationStatus(StrEnum):
    AWAITING_PRICING = "awaiting_pricing"  # raised by a PM; the QS prices it
    AWAITING_PM = "awaiting_pm"
    AWAITING_CLIENT = "awaiting_client"
    QUERIED = "queried"  # the PM or the client asked a question; the raiser or QS revises
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


OPEN_STATUSES = frozenset(
    {
        VariationStatus.AWAITING_PRICING,
        VariationStatus.AWAITING_PM,
        VariationStatus.AWAITING_CLIENT,
        VariationStatus.QUERIED,
    }
)

Approver = Literal["pm", "client"]
RaisedBy = Literal["pm", "qs"]
Decision = Literal["approve", "query", "reject"]


class TransitionError(ValueError):
    """The decision is not possible in the variation's current state."""


def default_limit(contract_value: Decimal) -> Decimal:
    return money(contract_value * DEFAULT_LIMIT_SHARE)


def needs_client(*, contract_change: Decimal, time_impact_days: int, limit: Decimal) -> bool:
    """BR-09: any time impact, or a contract change (up or down) above the limit."""
    return time_impact_days > 0 or abs(contract_change) > limit


def route(
    *,
    contract_change: Decimal,
    time_impact_days: int,
    limit: Decimal,
    raised_by: RaisedBy,
    seen_by_client: bool = False,
) -> Approver:
    """Who approves a priced variation. Once the client has seen it, a revision goes back to them."""
    if seen_by_client or needs_client(
        contract_change=contract_change, time_impact_days=time_impact_days, limit=limit
    ):
        return "client"
    return "pm" if raised_by == "qs" else "client"


def status_for(approver: Approver) -> VariationStatus:
    return VariationStatus.AWAITING_PM if approver == "pm" else VariationStatus.AWAITING_CLIENT


def next_status(*, status: str, decision: Decision, by: Approver) -> VariationStatus:
    """The state after a PM's or the client's decision. The client approves or queries (no reject)."""
    expected = VariationStatus.AWAITING_PM if by == "pm" else VariationStatus.AWAITING_CLIENT
    if status != expected:
        raise TransitionError(f"This variation is not waiting for the {'PM' if by == 'pm' else 'client'}.")
    if decision == "approve":
        return VariationStatus.APPROVED
    if decision == "query":
        return VariationStatus.QUERIED
    if by == "pm":
        return VariationStatus.REJECTED
    raise TransitionError("The client can approve a variation or query it.")


def check_budget_change(*, line_budget: Decimal, budget_change: Decimal) -> str | None:
    """A variation cannot take a section's cost budget below zero. None when it is fine."""
    if line_budget + budget_change < ZERO:
        return "This would take the section's budget below zero."
    return None
