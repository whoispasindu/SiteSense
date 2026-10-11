"""Progress claims, variation orders and the client's view of variations (Phase 8).

Money travels as decimal strings. The client's schema (``ClientVariationOut``) is separate and
carries no internal cost: no budget change, no section budget, no internal comments.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.rules.variations import VariationStatus
from app.schemas.materials import Comment, Notes, Quantity
from app.schemas.schedule import Percent

# A change to the contract or a budget: either way, within 16 digits.
MoneyChange = Annotated[Decimal, Field(ge=-(10**13), le=10**13, max_digits=16, decimal_places=2)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=160)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=5000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]

ClaimStatusName = Literal["submitted", "approved", "returned", "paid"]
ClaimAction = Literal["approve", "return", "record_payment"]
VariationStatusName = Literal[
    "awaiting_pricing", "awaiting_pm", "awaiting_client", "queried", "approved", "rejected", "withdrawn"
]
VariationAction = Literal["price", "revise", "approve", "query", "reject", "withdraw"]

assert set(VariationStatusName.__args__) == {s.value for s in VariationStatus}  # type: ignore[attr-defined]


def _blank_to_none(value: str | None) -> str | None:
    return value or None


# --- Progress claims (BR-08) -------------------------------------------------------------------------


class ClaimSectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: uuid.UUID
    certified_pct: Percent


class ClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[ClaimSectionIn] = Field(min_length=1, max_length=200)
    notes: Notes | None = None

    _notes = field_validator("notes")(_blank_to_none)


class ClaimSectionOut(BaseModel):
    section_id: uuid.UUID
    code: str
    name: str
    section_value: Decimal  # BOQ amount plus approved variations
    previous_pct: Decimal  # last approved claim
    certified_pct: Decimal | None = None  # this claim (None in the form before anything is entered)


class RuleOut(BaseModel):
    rule: str
    severity: str
    message: str
    facts: dict[str, str]


class ClaimFiguresOut(BaseModel):
    contract_value: Decimal
    certified_pct: Decimal  # rounded to 2 decimals for display
    certified_value: Decimal
    retention: Decimal
    retention_rate: Decimal  # 0.05 (BR-08)
    previous_claims: Decimal
    amount: Decimal


class ClaimCheckOut(BaseModel):
    figures: ClaimFiguresOut
    problems: list[RuleOut]


class ClaimOut(BaseModel):
    id: uuid.UUID
    number: str
    project_id: uuid.UUID
    status: ClaimStatusName
    figures: ClaimFiguresOut
    notes: str | None
    submitted_by: str
    submitted_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    decision_comment: str | None
    paid_on: date | None
    lines: list[ClaimSectionOut]
    actions: list[ClaimAction]


class ClaimsOverview(BaseModel):
    """A project's claims, and what a new claim starts from."""

    claims: list[ClaimOut]
    sections: list[ClaimSectionOut]  # for a new claim: values and the last approved percentages
    claimed_to_date: Decimal  # approved and paid claims
    retention_held: Decimal  # retention on the last approved claim
    paid_to_date: Decimal
    can_create: bool  # QS, and no claim is waiting for the PM


class ClaimDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "return"]
    comment: Comment | None = None

    _comment = field_validator("comment")(_blank_to_none)


class ClaimPaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paid_on: date


# --- Variation orders (BR-09) ------------------------------------------------------------------------


class VariationIn(BaseModel):
    """A new variation, or a revision of a queried one. Only the QS may include the price."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    description: Description
    section_id: uuid.UUID
    boq_item_id: uuid.UUID | None = None
    quantity_change: Quantity | None = None
    task_id: uuid.UUID | None = None
    time_impact_days: Annotated[int, Field(ge=0, le=3650)] = 0
    contract_change: MoneyChange | None = None
    budget_change: MoneyChange | None = None
    comment: Comment | None = None

    _comment = field_validator("comment")(_blank_to_none)


class VariationPriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_change: MoneyChange
    budget_change: MoneyChange
    comment: Comment | None = None

    _comment = field_validator("comment")(_blank_to_none)


class VariationDecisionIn(BaseModel):
    """The PM's decision: approve, query (back to the raiser and QS) or reject."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "query", "reject"]
    comment: Comment | None = None

    _comment = field_validator("comment")(_blank_to_none)


class ClientDecisionIn(BaseModel):
    """The client approves or queries (asks a question; the contractor revises)."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "query"]
    comment: Comment | None = None

    _comment = field_validator("comment")(_blank_to_none)


class WithdrawIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: Comment | None = None

    _comment = field_validator("comment")(_blank_to_none)


class VariationEventOut(BaseModel):
    action: str
    actor: str
    from_status: str | None
    to_status: str
    comment: str | None
    at: datetime


class VariationOut(BaseModel):
    id: uuid.UUID
    number: str
    project_id: uuid.UUID
    project_code: str
    title: str
    description: str
    section_id: uuid.UUID
    section: str
    boq_item_id: uuid.UUID | None
    boq_item: str | None
    quantity_change: Decimal | None
    task_id: uuid.UUID | None
    task: str | None
    time_impact_days: int
    contract_change: Decimal | None
    budget_change: Decimal | None
    status: VariationStatusName
    approver: Literal["pm", "client"] | None
    limit: Decimal  # the project's BR-09 limit now
    limit_applied: Decimal | None  # the limit when it was routed
    needs_client: bool | None  # None until priced
    raised_by: str
    raised_by_role: Literal["pm", "qs"]
    raised_at: datetime
    priced_by: str | None
    decided_at: datetime | None
    events: list[VariationEventOut]
    actions: list[VariationAction]


class VariationListOut(BaseModel):
    variations: list[VariationOut]
    limit: Decimal
    approved_contract_change: Decimal
    approved_time_impact_days: int


class ClientVariationOut(BaseModel):
    """What the client sees: no internal cost, no internal comments."""

    id: uuid.UUID
    number: str
    project_id: uuid.UUID
    project_code: str
    project_name: str
    title: str
    description: str
    contract_change: Decimal | None
    time_impact_days: int
    status: VariationStatusName
    limit: Decimal  # the project's BR-09 limit, shown to the client
    reason_for_client: str  # why it needs the client's approval
    raised_at: datetime
    events: list[VariationEventOut]
    can_decide: bool


# --- Company Admin: the BR-09 limit -----------------------------------------------------------------


class ProjectLimitOut(BaseModel):
    project_id: uuid.UUID
    code: str
    name: str
    site_code: str
    status: str
    variation_limit: Decimal


class ProjectLimitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variation_limit: Annotated[Decimal, Field(ge=0, le=10**13, max_digits=16, decimal_places=2)]
    reason: Reason


# --- Cost & claims overview (all of a PM's or QS's projects) ---------------------------------------


class ProjectCostOut(BaseModel):
    project_id: uuid.UUID
    code: str
    name: str
    status: str
    contract_value: Decimal  # includes approved variations
    approved_variations: Decimal
    budget: Decimal
    committed: Decimal
    forecast_final: Decimal
    variance: Decimal  # budget - forecast
    variance_pct: Decimal | None
    sections_over: int  # sections forecast more than 5% over budget
    claimed_to_date: Decimal
    open_claim: str | None  # number of the claim waiting for the PM
    variations_open: int


class WaitingItem(BaseModel):
    kind: Literal["claim", "variation"]
    id: uuid.UUID
    number: str
    project_id: uuid.UUID
    project_code: str
    title: str
    status: str
    since: datetime


class CostOverview(BaseModel):
    projects: list[ProjectCostOut]
    waiting_for_you: list[WaitingItem]  # claims to approve (PM), variations to price (QS) or decide (PM)
