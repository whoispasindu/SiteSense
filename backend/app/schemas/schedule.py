import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.project import ProjectCard, ProjectSummary


def _upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


TaskCode = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9.-]{0,15}$")]
TaskName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
Weight = Annotated[Decimal, Field(gt=0, le=100, max_digits=5, decimal_places=2)]
Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: TaskCode | None = None
    name: TaskName
    boq_section_id: uuid.UUID | None = None
    planned_start: date
    planned_end: date
    weight: Weight
    percent_complete: Percent = Decimal(0)
    is_critical: bool = False

    @model_validator(mode="after")
    def _dates_in_order(self) -> "TaskCreate":
        if self.planned_end < self.planned_start:
            raise ValueError("The planned end must be on or after the planned start.")
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
    is_critical: bool | None = None


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
    is_critical: bool
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
