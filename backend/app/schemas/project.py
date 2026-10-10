"""Project and BOQ schemas. Money and quantities travel as decimal strings, never floats."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from app.core.permissions import Role
from app.models.project import ProjectStatus, ProjectType
from app.schemas.auth import SiteSummary


def _upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


ProjectCode = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9-]{1,23}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
Money = Annotated[Decimal, Field(max_digits=16, decimal_places=2)]

# Longest contract period accepted. It bounds every week-by-week calculation (S-curves), so an
# absurd date such as 9999-12-31 cannot turn one request into minutes of work.
MAX_PROJECT_DAYS = 15 * 366


# Planned average crew on site; the risk model compares reported crews with it.
PlannedCrew = Annotated[int, Field(ge=1, le=5000)]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ProjectCode
    name: Name
    site_id: uuid.UUID
    client_name: Name
    project_type: ProjectType
    status: ProjectStatus = ProjectStatus.PLANNING
    contract_value: Annotated[Money, Field(gt=0)]
    start_date: date
    planned_end: date
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    planned_crew: PlannedCrew | None = None

    @model_validator(mode="after")
    def _dates_in_order(self) -> "ProjectCreate":
        if self.planned_end < self.start_date:
            raise ValueError("The planned end date must be on or after the start date.")
        if (self.planned_end - self.start_date).days > MAX_PROJECT_DAYS:
            raise ValueError("A project can run for at most 15 years.")
        return self


class ProjectUpdate(BaseModel):
    """Code and site are fixed after creation: the site decides who can see the project."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    client_name: Name | None = None
    project_type: ProjectType | None = None
    status: ProjectStatus | None = None
    contract_value: Annotated[Money, Field(gt=0)] | None = None
    start_date: date | None = None
    planned_end: date | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    planned_crew: PlannedCrew | None = None


# Each response comes in two shapes. The base classes carry no rates or amounts and are what site
# engineers receive; the subclasses add the cost fields for roles with ``rates:read`` (PM, QS,
# procurement). See ``app.services.visibility``.


class ProjectCard(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    site: SiteSummary
    client_name: str
    project_type: ProjectType
    status: ProjectStatus
    start_date: date
    planned_end: date
    item_count: int


class ProjectSummary(ProjectCard):
    contract_value: Decimal
    boq_total: Decimal
    budget_total: Decimal


class SectionBasics(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    item_count: int


class SectionTotals(SectionBasics):
    amount: Decimal
    budget_line_id: uuid.UUID
    budget_amount: Decimal


class TeamMember(BaseModel):
    id: uuid.UUID
    full_name: str
    role: Role
    role_label: str


class ProjectDetailBasics(ProjectCard):
    description: str | None
    planned_crew: int | None
    sections: list[SectionBasics]
    team: list[TeamMember]
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectSummary):
    description: str | None
    planned_crew: int | None
    sections: list[SectionTotals]
    team: list[TeamMember]
    created_at: datetime
    updated_at: datetime


class BoqItemBasics(BaseModel):
    id: uuid.UUID
    item_code: str
    description: str
    unit: str
    quantity: Decimal
    # Live material requests for the item (everything except rejected and cancelled).
    requested_quantity: Decimal
    remaining_quantity: Decimal


class BoqItemOut(BoqItemBasics):
    rate: Decimal
    amount: Decimal


class BoqSectionBasics(SectionBasics):
    items: list[BoqItemBasics]


class BoqSectionOut(SectionTotals):
    items: list[BoqItemOut]


class BoqBasics(BaseModel):
    project_id: uuid.UUID
    sections: list[BoqSectionBasics]
    item_count: int


class BoqOut(BaseModel):
    project_id: uuid.UUID
    sections: list[BoqSectionOut]
    boq_total: Decimal
    budget_total: Decimal
    item_count: int


class BudgetLineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_amount: Annotated[Money, Field(ge=0)]


# --- Import report --------------------------------------------------------------------------


class CellErrorOut(BaseModel):
    column: str
    message: str


class RowResultOut(BaseModel):
    row: int
    status: Literal["ok", "skipped", "error"]
    section_code: str | None
    item_code: str | None
    description: str | None
    errors: list[CellErrorOut]


class SectionPreview(BaseModel):
    code: str
    name: str
    items: int
    amount: Decimal
    budget: Decimal


class ImportReport(BaseModel):
    file_name: str
    imported: bool
    dry_run: bool
    total_rows: int
    ok_rows: int
    error_rows: int
    skipped_rows: int
    has_budget_rates: bool
    replaces_items: int
    boq_total: Decimal
    budget_total: Decimal
    sections: list[SectionPreview]
    rows: list[RowResultOut]
