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
    unit_price: Price
    needed_by: date
    notes: Notes | None = None

    _notes = field_validator("notes")(_blank_to_none)


class RequestCheck(BaseModel):
    """The same fields as a new request, checked against the rules without saving anything."""

    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    boq_item_id: uuid.UUID
    quantity: Quantity
    unit_price: Price


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

    _comment = field_validator("comment")(_blank_to_none)


class RuleResultOut(BaseModel):
    rule: str
    severity: Literal["pass", "warn", "block"]
    message: str
    facts: dict[str, str]


class RuleCheckOut(BaseModel):
    approval_level: Literal["qs", "pm"]
    blocked: bool
    results: list[RuleResultOut]
    budget_rate: Decimal
    amount: Decimal


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


class RequestSummary(BaseModel):
    id: uuid.UUID
    number: str
    project: ProjectRef
    boq_item: BoqItemRef
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    needed_by: date
    status: Status
    approval_level: Literal["qs", "pm"]
    requested_by: PersonOut
    submitted_at: datetime
    updated_at: datetime


class RequestList(BaseModel):
    items: list[RequestSummary]
    total: int
    # Pipeline counts for the caller's scope (and project filter), by status.
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


class OrderRef(BaseModel):
    id: uuid.UUID
    number: str
    supplier_name: str
    unit_price: Decimal
    amount: Decimal
    expected_delivery: date
    delivered_quantity: Decimal
    deliveries: list[DeliveryOut]


class RequestDetail(RequestSummary):
    notes: str | None
    boq_quantity: Decimal
    rules: RuleCheckOut
    history: list[HistoryEntry]
    order: OrderRef | None
    # What the caller may do now, e.g. ["approve", "reject", "request_change"].
    actions: list[Action]


class BoqItemOption(BaseModel):
    """A BOQ item in the request form's picker, with what is left to request."""

    id: uuid.UUID
    item_code: str
    description: str
    unit: str
    section_code: str
    section_name: str
    boq_quantity: Decimal
    requested_quantity: Decimal
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


class OrderLineOut(BaseModel):
    id: uuid.UUID
    request_id: uuid.UUID
    request_number: str
    item_code: str
    description: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    delivered_quantity: Decimal


class PurchaseOrderSummary(BaseModel):
    id: uuid.UUID
    number: str
    project: ProjectRef
    supplier: SupplierOut
    status: Literal["issued", "part_delivered", "delivered"]
    total: Decimal
    issued_at: datetime
    expected_delivery: date
    issued_by: PersonOut


class PurchaseOrderDetail(PurchaseOrderSummary):
    notes: str | None
    lines: list[OrderLineOut]
    deliveries: list[DeliveryOut]


# --- Budget ----------------------------------------------------------------------------------------


class BudgetFigures(BaseModel):
    boq_amount: Decimal
    budget: Decimal
    approved: Decimal  # approved requests not yet on a purchase order
    committed: Decimal  # ordered, not yet delivered
    spent: Decimal  # delivered
    remaining: Decimal  # budget - committed - spent
    forecast: Decimal  # spent + committed + approved
    variance: Decimal  # budget - forecast (negative: over budget)


class BudgetLineOut(BudgetFigures):
    section_id: uuid.UUID
    code: str
    name: str


class BudgetOut(BaseModel):
    project_id: uuid.UUID
    lines: list[BudgetLineOut]
    totals: BudgetFigures
