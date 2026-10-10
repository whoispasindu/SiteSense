import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.models.materials import RequestStatus

# TC-04: zero or negative quantities and prices are validation errors.
Quantity = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
Price = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
ContactName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9 +()-]{7,32}$")]
Categories = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]

Status = Literal[
    "requested",
    "pm_approval",
    "approved",
    "ordered",
    "delivered",
    "rejected",
    "change_requested",
    "cancelled",
]
Decision = Literal["approve", "reject", "request_change", "cancel"]
Action = Literal["approve", "reject", "request_change", "cancel", "edit", "order"]

assert set(Status.__args__) == {s.value for s in RequestStatus}  # type: ignore[attr-defined]


def _blank_to_none(value: str | None) -> str | None:
    return value or None


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    boq_item_id: uuid.UUID
    quantity: Quantity
    # Expected unit price. Only roles that see rates may give one. Without it (always the case for
    # site engineers) the price is pending and the QS enters the quoted price at the QS check.
    unit_price: Price | None = None
    needed_by: date
    notes: Notes | None = None

    _notes = field_validator("notes")(_blank_to_none)


class RequestCheck(BaseModel):
    """The same fields as a new request, checked against the rules without saving anything."""

    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    boq_item_id: uuid.UUID
    quantity: Quantity
    unit_price: Price | None = None


class RequestUpdate(BaseModel):
    """The requester's changes after "change requested"; saving resubmits the request."""

    model_config = ConfigDict(extra="forbid")

    quantity: Quantity | None = None
    unit_price: Price | None = None
    needed_by: date | None = None
    notes: Notes | None = None
    comment: Comment | None = None

    _notes = field_validator("notes")(_blank_to_none)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision
    comment: Comment | None = None
    # The quoted unit price, set by the QS when approving at the QS check (required if pending).
    unit_price: Price | None = None

    _comment = field_validator("comment")(_blank_to_none)


class RuleResultOut(BaseModel):
    rule: str
    severity: Literal["pass", "warn", "block", "pending"]
    message: str
    facts: dict[str, str]


# Rules whose results carry prices or amounts. Viewers without ``rates:read`` never receive them.
COST_RULES = frozenset({"BR-01", "BR-13"})


class RuleCheckBasics(BaseModel):
    approval_level: Literal["qs", "pm"]
    blocked: bool
    results: list[RuleResultOut]
    # The rules that sent the request to the project manager (BR-01, BR-13), if any.
    routed_by: list[str]

    @field_validator("results")
    @classmethod
    def _no_cost_rules(cls, value: list[RuleResultOut]) -> list[RuleResultOut]:
        return [r for r in value if r.rule not in COST_RULES]


class RuleCheckOut(RuleCheckBasics):
    budget_rate: Decimal
    amount: Decimal | None  # None while the price is pending

    @field_validator("results")
    @classmethod
    def _no_cost_rules(cls, value: list[RuleResultOut]) -> list[RuleResultOut]:
        return value  # full results for viewers who see rates


class PersonOut(BaseModel):
    id: uuid.UUID
    full_name: str


class BoqItemRef(BaseModel):
    id: uuid.UUID
    item_code: str
    description: str
    unit: str
    section_code: str


class ProjectRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    site_code: str


# Responses come in two shapes: the base classes carry no rates or amounts (site engineers); the
# subclasses add them for roles with ``rates:read``. See ``app.services.visibility``.


class RequestSummaryBasics(BaseModel):
    id: uuid.UUID
    number: str
    project: ProjectRef
    boq_item: BoqItemRef
    quantity: Decimal
    needed_by: date
    status: Status
    approval_level: Literal["qs", "pm"]
    requested_by: PersonOut
    submitted_at: datetime
    updated_at: datetime


class RequestSummary(RequestSummaryBasics):
    # None while the price is pending: the QS enters the quoted price at the QS check.
    unit_price: Decimal | None
    amount: Decimal | None


class RequestListBasics(BaseModel):
    items: list[RequestSummaryBasics]
    total: int
    # Pipeline counts for the caller's scope (and project filter), by status.
    counts: dict[str, int]


class RequestList(BaseModel):
    items: list[RequestSummary]
    total: int
    counts: dict[str, int]


class HistoryEntry(BaseModel):
    action: str
    from_status: str | None
    to_status: str
    comment: str | None
    actor: PersonOut
    created_at: datetime


class DeliveryOut(BaseModel):
    id: uuid.UUID
    quantity: Decimal
    delivered_on: date
    notes: str | None
    created_at: datetime
    # Set on purchase-order views, where one order has several lines.
    request_number: str | None = None
    unit: str | None = None


class OrderRefBasics(BaseModel):
    id: uuid.UUID
    number: str
    supplier_name: str
    expected_delivery: date
    delivered_quantity: Decimal
    deliveries: list[DeliveryOut]


class OrderRef(OrderRefBasics):
    unit_price: Decimal
    amount: Decimal


class RequestDetailBasics(RequestSummaryBasics):
    notes: str | None
    boq_quantity: Decimal
    rules: RuleCheckBasics
    history: list[HistoryEntry]
    order: OrderRefBasics | None
    # What the caller may do now, e.g. ["approve", "reject", "request_change"].
    actions: list[Action]


class RequestDetail(RequestSummary):
    notes: str | None
    boq_quantity: Decimal
    rules: RuleCheckOut
    history: list[HistoryEntry]
    order: OrderRef | None
    actions: list[Action]


class BoqItemOptionBasics(BaseModel):
    """A BOQ item in the request form's picker, with what is left to request."""

    id: uuid.UUID
    item_code: str
    description: str
    unit: str
    section_code: str
    section_name: str
    boq_quantity: Decimal
    requested_quantity: Decimal
    remaining_quantity: Decimal


class BoqItemOption(BoqItemOptionBasics):
    budget_rate: Decimal


# --- Suppliers, purchase orders, deliveries ----------------------------------------------------------


class SupplierIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    contact_name: ContactName | None = None
    phone: Phone | None = None
    email: EmailStr | None = None
    categories: Categories | None = None


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    contact_name: ContactName | None = None
    phone: Phone | None = None
    email: EmailStr | None = None
    categories: Categories | None = None
    is_active: bool | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    contact_name: str | None
    phone: str | None
    email: str | None
    categories: str | None
    is_active: bool


class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID
    # Agreed price; defaults to the approved request price and may not exceed it.
    unit_price: Price | None = None


class PurchaseOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: uuid.UUID
    expected_delivery: date
    notes: Notes | None = None
    lines: list[OrderLineIn] = Field(min_length=1, max_length=50)

    _notes = field_validator("notes")(_blank_to_none)

    @field_validator("lines")
    @classmethod
    def _unique(cls, value: list[OrderLineIn]) -> list[OrderLineIn]:
        if len({line.request_id for line in value}) != len(value):
            raise ValueError("Each request can appear only once.")
        return value


class DeliveryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID
    quantity: Quantity
    delivered_on: date
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class OrderLineBasics(BaseModel):
    id: uuid.UUID
    request_id: uuid.UUID
    request_number: str
    item_code: str
    description: str
    unit: str
    quantity: Decimal
    delivered_quantity: Decimal


class OrderLineOut(OrderLineBasics):
    unit_price: Decimal
    amount: Decimal


class PurchaseOrderSummaryBasics(BaseModel):
    id: uuid.UUID
    number: str
    project: ProjectRef
    supplier: SupplierOut
    status: Literal["issued", "part_delivered", "delivered"]
    issued_at: datetime
    expected_delivery: date
    issued_by: PersonOut


class PurchaseOrderSummary(PurchaseOrderSummaryBasics):
    total: Decimal


class PurchaseOrderDetailBasics(PurchaseOrderSummaryBasics):
    notes: str | None
    lines: list[OrderLineBasics]
    deliveries: list[DeliveryOut]


class PurchaseOrderDetail(PurchaseOrderSummary):
    notes: str | None
    lines: list[OrderLineOut]
    deliveries: list[DeliveryOut]


class ReturnedLineOut(BaseModel):
    """A request sent back to the PM at order time (BR-13 or BR-14), at the quoted price."""

    request_id: uuid.UUID
    number: str
    unit_price: Decimal
    rules: list[RuleResultOut]


class OrderResult(BaseModel):
    """What issuing a purchase order did: the order (if any line could be ordered) and the lines
    that went back for project manager approval instead."""

    order: PurchaseOrderDetail | None
    returned: list[ReturnedLineOut]


# --- Budget ----------------------------------------------------------------------------------------


class BudgetFigures(BaseModel):
    boq_amount: Decimal
    budget: Decimal
    approved: Decimal  # approved requests not yet on a purchase order
    on_order: Decimal  # ordered, not yet delivered
    spent: Decimal  # delivered
    # Cumulative: every approved, ordered or delivered request once, at its latest value (BR-13).
    committed: Decimal
    remaining: Decimal  # budget - committed (negative: over budget)


class BudgetLineOut(BudgetFigures):
    section_id: uuid.UUID
    code: str
    name: str


class BudgetOut(BaseModel):
    project_id: uuid.UUID
    lines: list[BudgetLineOut]
    totals: BudgetFigures
