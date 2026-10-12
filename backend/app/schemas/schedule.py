import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

from app.schemas.project import ProjectCard, ProjectSummary


def _upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


TaskCode = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9.-]{0,15}$")]
TaskName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
Weight = Annotated[Decimal, Field(gt=0, le=100, max_digits=5, decimal_places=2)]
Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
# Phase 12: what the client calls a milestone, e.g. "Structure complete".
MilestoneName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: TaskCode | None = None
    name: TaskName
    boq_section_id: uuid.UUID | None = None
    planned_start: date
    planned_end: date
    weight: Weight
    percent_complete: Percent = Decimal(0)
    # BR-06: flagged when heavy rain is forecast on a working day of its window.
    is_concrete_pour: bool = False
    # Phase 12: shown to the client as a milestone (project managers only).
    client_milestone: StrictBool = False
    milestone_name: MilestoneName | None = None

    @model_validator(mode="after")
    def _dates_in_order(self) -> "TaskCreate":
        if self.planned_end < self.planned_start:
            raise ValueError("The planned end must be on or after the planned start.")
        if self.milestone_name and not self.client_milestone:
            raise ValueError("A milestone name needs the task to be a client milestone.")
        return self


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: TaskCode | None = None
    name: TaskName | None = None
    boq_section_id: uuid.UUID | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    weight: Weight | None = None
    percent_complete: Percent | None = None
    is_concrete_pour: bool | None = None
    client_milestone: StrictBool | None = None
    milestone_name: MilestoneName | None = None


TaskState = Literal["not_started", "on_track", "behind", "done"]


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    code: str | None
    name: str
    boq_section_id: uuid.UUID | None
    boq_section_code: str | None
    planned_start: date
    planned_end: date
    weight: Decimal
    percent_complete: Decimal
    is_critical: bool  # on the forecast critical path (Phase 9: calculated, never set by hand)
    is_concrete_pour: bool
    client_milestone: bool  # Phase 12: shown to the client
    milestone_name: str | None  # the client-friendly name, if the PM gave one
    stopped: bool  # BR-11: a stop-work flag stops it
    actual_start: date | None
    actual_finish: date | None
    position: int
    # How far the task should be by today, per the plan (0-100).
    planned_percent_today: float
    state: TaskState
    progress_updated_at: datetime | None


class TaskList(BaseModel):
    tasks: list[TaskOut]
    weight_total: Decimal


class CurvePointOut(BaseModel):
    date: date
    planned: float
    actual: float | None


class ProgressOut(BaseModel):
    as_of: date
    planned_percent: float
    actual_percent: float
    # Actual minus planned, in percentage points: negative means behind the plan.
    variance: float
    weight_total: Decimal
    task_count: int
    programme_start: date
    programme_end: date
    contract_end: date
    points: list[CurvePointOut]


class ScheduleSummaryBasics(BaseModel):
    """For viewers without ``rates:read``: the project without its contract value or totals."""

    project: ProjectCard
    planned_percent: float
    actual_percent: float
    variance: float
    task_count: int


class ScheduleSummary(ScheduleSummaryBasics):
    project: ProjectSummary


# --- Phase 9: dependencies, the network, holidays ------------------------------------------------


class DependencyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predecessor_id: uuid.UUID
    successor_id: uuid.UUID
    lag_days: Annotated[int, Field(ge=0, le=365)] = 0


class DependencyOut(BaseModel):
    id: uuid.UUID
    predecessor_id: uuid.UUID
    successor_id: uuid.UUID
    lag_days: int


class TaskTimingOut(BaseModel):
    task_id: uuid.UUID
    code: str | None
    name: str
    percent_complete: Decimal
    planned_start: date
    planned_end: date
    planned_duration: int  # working days
    forecast_start: date
    forecast_finish: date
    slip_days: int  # working days the forecast finish is after the planned end (negative: early)
    total_float: int  # working days, on the forecast network
    is_critical: bool
    is_done: bool
    stopped: bool  # BR-11
    stopped_days: int  # working days stopped so far
    is_concrete_pour: bool
    rain_days: list[date]  # BR-06: heavy-rain working days forecast in its window
    predecessors: list[uuid.UUID]


class StopWorkOut(BaseModel):
    action_id: uuid.UUID
    report_id: uuid.UUID
    summary: str
    scope: Literal["tasks", "project"]
    task_ids: list[uuid.UUID]
    since: datetime


class NetworkOut(BaseModel):
    """The Gantt view: planned and forecast dates, the critical path, flags, on the working calendar."""

    project_id: uuid.UUID
    as_of: date
    working_week: str
    planned_end: date  # the contract's planned end (moves with approved variations)
    network_end: date | None  # the plan's own end through the dependencies
    forecast_end: date | None
    slip_days: int  # working days the forecast end is after the planned end
    tasks: list[TaskTimingOut]
    dependencies: list[DependencyOut]
    stop_work: list[StopWorkOut]
    warnings: list[str]  # e.g. no holidays entered for a year the programme runs into


class HolidayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holiday_date: Annotated[date, Field(ge=date(2000, 1, 1), le=date(2100, 12, 31))]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]


class HolidayOut(BaseModel):
    id: uuid.UUID
    holiday_date: date
    name: str


class HolidayList(BaseModel):
    holidays: list[HolidayOut]
    years: list[int]  # years that have at least one holiday
    missing_next_year: bool  # warn the Company Admin when next year's list is not entered
