"""The client portal (Phase 12) and the project manager's side of it.

Client schemas are their own classes, never subclasses of internal ones, so a field added to an
internal response can never reach a client by inheritance. They carry no budget, cost, rate, risk
score or internal comment; ``tests/test_client_portal.py`` checks every field name, at any depth.
What the client does see is the contract they signed: the contract value (with approved variations)
and the progress claims the project manager has approved.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
MilestoneStatus = Literal["done", "on_track", "late", "not_started"]

# --- The client's view ----------------------------------------------------------------------------------


class ClientHandoverChange(BaseModel):
    handover_date: date
    reason: str
    published_at: datetime


class ClientHandover(BaseModel):
    contract_end: date  # the contract's planned end, moved only by approved variations
    published_date: date | None  # the project manager's published forecast; None: not published yet
    reason: str | None
    published_at: datetime | None
    history: list[ClientHandoverChange]  # earlier published dates, newest first


class ClientMilestone(BaseModel):
    name: str
    planned_date: date
    expected_date: date  # the programme's forecast, never after the published handover date
    completed_on: date | None
    percent_complete: float
    status: MilestoneStatus


class ClientProgressPoint(BaseModel):
    date: date
    planned: float
    actual: float | None


class ClientPhoto(BaseModel):
    id: uuid.UUID
    caption: str | None
    taken_on: date  # the date of the daily report it came from
    width: int
    height: int


class ClientProjectCard(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    location: str
    status: str
    planned_percent: float
    actual_percent: float
    handover_date: date  # published if there is one, otherwise the contract's planned end
    handover_published: bool
    variations_waiting: int  # variations waiting for the client's decision


class ClientProject(ClientProjectCard):
    start_date: date
    handover: ClientHandover
    progress: list[ClientProgressPoint]
    milestones: list[ClientMilestone]
    photos: list[ClientPhoto]


class ClientClaim(BaseModel):
    number: str
    status: Literal["approved", "paid"]
    certified_pct: Decimal
    certified_value: Decimal
    retention: Decimal  # held back so far, as at this claim (retention is cumulative)
    previous_claims: Decimal
    amount: Decimal  # due for this claim
    approved_on: date
    paid_on: date | None


class RetentionRelease(BaseModel):
    """When the retention is due back: the end of the defects period after handover."""

    defects_period_months: int
    handover_date: date  # the published handover date, or the contract's planned end before one
    handover_published: bool
    expected_on: date


class ClientClaims(BaseModel):
    project_id: uuid.UUID
    original_contract_value: Decimal
    approved_variations: Decimal
    contract_value: Decimal  # with approved variations
    claimed_to_date: Decimal  # approved and paid claims
    paid_to_date: Decimal
    retention_held: Decimal  # running total held back so far
    retention_release: RetentionRelease
    retention_note: str
    claims: list[ClientClaim]  # newest first


# --- The project manager's side ------------------------------------------------------------------------


class HandoverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handover_date: date
    reason: Reason


class HandoverEntryOut(BaseModel):
    kind: Literal["published", "confirmed"]
    handover_date: date
    reason: str
    programme_forecast: date | None
    published_by: str
    published_at: datetime


class DateRange(BaseModel):
    start: date
    end: date


class HandoverSuggestions(BaseModel):
    contract_end: date
    programme_forecast: date | None  # at current rates (Phase 9)
    risk_range: DateRange | None  # the risk model's likely range (risk:read only)


class HandoverReminder(BaseModel):
    """Why the published date may be out of date (shown on the PM's dashboard)."""

    reasons: list[str]
    forecast_gap_days: int | None  # working days the programme forecast is after the published date
    days_since_review: int


class HandoverState(BaseModel):
    project_id: uuid.UUID
    current: HandoverEntryOut | None  # the latest publication or review
    published: HandoverEntryOut | None  # the latest published date: what the client sees
    history: list[HandoverEntryOut]  # newest first
    suggestions: HandoverSuggestions
    reminder: HandoverReminder | None
    can_publish: bool


class HandoverReminderItem(BaseModel):
    project_id: uuid.UUID
    code: str
    name: str
    published_date: date
    reminder: HandoverReminder


class PhotoShareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shared: StrictBool


class PhotosShareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    shared: StrictBool


class ProjectPhotoOut(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    report_date: date
    caption: str | None
    width: int
    height: int
    shared_with_client: bool
    shared_at: datetime | None


class ProjectPhotos(BaseModel):
    items: list[ProjectPhotoOut]
    total: int
    shared: int
