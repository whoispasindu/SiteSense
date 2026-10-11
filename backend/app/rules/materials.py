"""Material request rules (BR-01, BR-02, BR-04, BR-05, BR-13, BR-14) and the approval states.

Pure functions over plain values: no database, no clock, no request. Services gather the facts and
call these, so every rule is tested on its own (``tests/test_rules_materials.py``) and documented in
``docs/business-rules.md``.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

PRICE_TOLERANCE = Decimal("0.05")  # BR-01: the QS may approve up to 5% over budget
QUANTITY_TOLERANCE = Decimal("0.03")  # BR-02: up to 3% over the BOQ quantity
CENTS = Decimal("0.01")
ZERO = Decimal(0)

ApprovalLevel = Literal["qs", "pm"]
# "pending": the rule cannot be evaluated yet because the price has not been entered.
Severity = Literal["pass", "warn", "block", "pending"]


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule: str
    severity: Severity
    message: str
    facts: dict[str, str] = field(default_factory=dict)

    @property
    def blocks(self) -> bool:
        return self.severity == "block"


def _pct(value: Decimal) -> str:
    return f"{(value * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def _qty(value: Decimal) -> str:
    """1650.000 -> "1,650"; 12.500 -> "12.5" (for messages; facts keep the exact value)."""
    text = f"{value.quantize(Decimal('0.001')):,f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


# --- BR-02: quantity against the BOQ allowance ---------------------------------------------------


def check_quantity(
    *,
    boq_quantity: Decimal,
    already_requested: Decimal,
    requested: Decimal,
    approved_variation: Decimal = ZERO,
) -> RuleResult:
    """Block when everything requested for the item would exceed the BOQ quantity plus 3%.

    ``already_requested`` counts every live request for the item (not rejected or cancelled).
    ``approved_variation`` is extra quantity from approved variation orders on the item (Phase 8).
    """
    allowance = boq_quantity * (1 + QUANTITY_TOLERANCE) + approved_variation
    total = already_requested + requested
    facts = {
        "boq_quantity": str(boq_quantity),
        "allowance": str(allowance.quantize(Decimal("0.001"))),
        "already_requested": str(already_requested),
        "total_after_request": str(total),
        "approved_variation": str(approved_variation),
    }
    if total > allowance:
        over = total - boq_quantity
        return RuleResult(
            "BR-02",
            "block",
            f"This would bring requests for the item to {_qty(total)} against a BOQ quantity of "
            f"{_qty(boq_quantity)} "
            f"({_pct(over / boq_quantity)} over; the limit is 3%). An approved variation is needed first.",
            facts,
        )
    if total > boq_quantity * (1 + QUANTITY_TOLERANCE):
        return RuleResult(
            "BR-02",
            "pass",
            f"Covered by approved variations: {_qty(total)} requested against a BOQ quantity of "
            f"{_qty(boq_quantity)} plus {_qty(approved_variation)} from variations.",
            facts,
        )
    if total > boq_quantity:
        return RuleResult(
            "BR-02",
            "warn",
            f"Within the 3% tolerance: {_qty(total)} requested against a BOQ quantity of "
            f"{_qty(boq_quantity)}.",
            facts,
        )
    message = f"{_qty(total)} of {_qty(boq_quantity)} requested so far for this item, including this one."
    return RuleResult("BR-02", "pass", message, facts)


# --- BR-01: price against the budget line, and who approves ----------------------------------------


def item_budget_rate(*, item_rate: Decimal, section_amount: Decimal, line_budget: Decimal) -> Decimal:
    """The cost budget per unit for a BOQ item: its share of the section's budget line.

    The budget line is the section's cost budget; items carry contract rates. Scaling the contract
    rate by budget / BOQ value gives the budgeted cost per unit.
    """
    if section_amount <= 0:
        return ZERO
    return item_rate * line_budget / section_amount


PRICE_PENDING = "Price pending: the QS enters the quoted price at the QS check."


def check_price(*, unit_price: Decimal | None, budget_rate: Decimal) -> RuleResult:
    """BR-01: a unit price more than 5% above the item's budgeted rate needs the project manager.

    Only the price is compared here; the section's budget as a whole is BR-13.
    """
    if unit_price is None:
        return RuleResult("BR-01", "pending", PRICE_PENDING, {"budget_rate": str(money(budget_rate))})
    price_over = (unit_price - budget_rate) / budget_rate if budget_rate > 0 else Decimal(1)
    facts = {
        "unit_price": str(unit_price),
        "budget_rate": str(money(budget_rate)),
        "price_over": _pct(price_over),
    }
    if budget_rate <= 0:
        return RuleResult(
            "BR-01", "warn", "Needs project manager approval: the item has no budgeted rate.", facts
        )
    if price_over > PRICE_TOLERANCE:
        message = (
            f"Needs project manager approval: the price is {_pct(price_over)} above the budgeted rate "
            "(limit 5%)."
        )
        return RuleResult("BR-01", "warn", message, facts)
    if price_over > 0:
        return RuleResult(
            "BR-01", "pass", f"{_pct(price_over)} above the budgeted rate: within the 5% limit.", facts
        )
    return RuleResult("BR-01", "pass", "At or below the budgeted rate.", facts)


# --- BR-13: the section's budget line ----------------------------------------------------------------


def check_section_budget(
    *, line_budget: Decimal, line_committed: Decimal, request_amount: Decimal | None
) -> RuleResult:
    """BR-13: if the section's committed cost plus this request exceeds its budget line, the PM approves.

    ``line_committed`` is the section's committed cost: every other request counted once at its
    latest value (delivered, else on order, else approved), pending requests excluded. There is
    no tolerance: any excess needs the project manager.
    """
    if request_amount is None:
        facts = {"line_budget": str(money(line_budget)), "line_committed": str(money(line_committed))}
        return RuleResult("BR-13", "pending", PRICE_PENDING, facts)
    after = line_committed + request_amount
    facts = {
        "line_budget": str(money(line_budget)),
        "line_committed": str(money(line_committed)),
        "line_after_request": str(money(after)),
        "line_over": str(money(max(after - line_budget, ZERO))),
    }
    if after > line_budget:
        message = (
            f"Needs project manager approval: with this request the section's committed cost would be "
            f"LKR {money(after):,} against a budget line of LKR {money(line_budget):,}."
        )
        return RuleResult("BR-13", "warn", message, facts)
    return RuleResult("BR-13", "pass", "The section stays within its budget line.", facts)


def route_approval(
    *,
    unit_price: Decimal | None,
    budget_rate: Decimal,
    request_amount: Decimal | None,
    line_budget: Decimal,
    line_committed: Decimal,
) -> tuple[ApprovalLevel, list[RuleResult], list[str]]:
    """Who approves: the QS, unless BR-01 or BR-13 fires. Returns the level, both results and the
    ids of the rules that sent the request to the project manager."""
    results = [
        check_price(unit_price=unit_price, budget_rate=budget_rate),
        check_section_budget(
            line_budget=line_budget, line_committed=line_committed, request_amount=request_amount
        ),
    ]
    fired = [r.rule for r in results if r.severity == "warn"]
    return ("pm" if fired else "qs"), results, fired


# --- BR-14: the price on the purchase order ----------------------------------------------------------


def check_order_price(*, approved_price: Decimal, order_price: Decimal) -> RuleResult:
    """BR-14: a purchase-order price more than 5% above the approved price goes back to the PM.

    Up to 5% above is accepted at ordering (normal quote movement); anything more needs a fresh
    project manager approval at the new price before it can be ordered.
    """
    over = (order_price - approved_price) / approved_price
    facts = {"approved_price": str(approved_price), "order_price": str(order_price), "price_over": _pct(over)}
    if over > PRICE_TOLERANCE:
        message = (
            f"The order price is {_pct(over)} above the approved price (limit 5%): sent back for "
            "project manager approval."
        )
        return RuleResult("BR-14", "warn", message, facts)
    return RuleResult("BR-14", "pass", "The order price is within 5% of the approved price.", facts)


# --- BR-04: segregation of duties ------------------------------------------------------------------


def check_not_own_request(*, actor_id: object, requester_id: object) -> RuleResult:
    if actor_id == requester_id:
        return RuleResult("BR-04", "block", "You cannot approve or reject a request you raised yourself.")
    return RuleResult("BR-04", "pass", "The approver is not the requester.")


# --- BR-05: no purchase order before the approval chain is complete --------------------------------


def check_can_order(*, status: str) -> RuleResult:
    if status != "approved":
        message = "Only approved requests can go on a purchase order; this one is not approved yet."
        return RuleResult("BR-05", "block", message)
    return RuleResult("BR-05", "pass", "Approval chain complete.")


# --- Approval state machine ------------------------------------------------------------------------

Decision = Literal["approve", "reject", "request_change", "cancel", "resubmit"]
Stage = Literal["qs", "pm", "requester"]

# (status, decision, stage) -> next status. "approve" at the QS stage depends on the routing level.
_TRANSITIONS: dict[tuple[str, str, str], str] = {
    ("requested", "reject", "qs"): "rejected",
    ("requested", "request_change", "qs"): "change_requested",
    ("pm_approval", "approve", "pm"): "approved",
    ("pm_approval", "reject", "pm"): "rejected",
    ("pm_approval", "request_change", "pm"): "change_requested",
    ("change_requested", "resubmit", "requester"): "requested",
    ("requested", "cancel", "requester"): "cancelled",
    ("pm_approval", "cancel", "requester"): "cancelled",
    ("change_requested", "cancel", "requester"): "cancelled",
}


class TransitionError(ValueError):
    pass


def next_status(*, status: str, decision: Decision, stage: Stage, approval_level: ApprovalLevel) -> str:
    """The status after a decision, or TransitionError if the decision is not allowed now."""
    if (status, decision, stage) == ("requested", "approve", "qs"):
        return "approved" if approval_level == "qs" else "pm_approval"
    target = _TRANSITIONS.get((status, decision, stage))
    if target is None:
        state = status.replace("_", " ")
        raise TransitionError(f"A request that is {state} cannot be given '{decision}' now.")
    return target


_STAGES: dict[str, Stage] = {"requested": "qs", "pm_approval": "pm", "change_requested": "requester"}


def stage_for(status: str) -> Stage | None:
    """Who acts next on a request in this status (None: nobody, it is with procurement or closed)."""
    return _STAGES.get(status)
