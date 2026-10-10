import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.schedule import Percent

MAX_PROGRESS_ENTRIES = 100

WorkDone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=5000)]
Problems = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
WeatherSummary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Temperature = Annotated[Decimal, Field(ge=-60, le=70, max_digits=4, decimal_places=1)]
Rainfall = Annotated[Decimal, Field(ge=0, le=2000, max_digits=6, decimal_places=1)]
CrewCount = Annotated[int, Field(ge=0, le=5000)]
WeatherSource = Literal["forecast", "manual"]


class ProgressEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    percent_complete: Percent


class WeatherFields(BaseModel):
    """Weather on the day. All optional: omitted fields are filled from the cached forecast."""

    model_config = ConfigDict(extra="forbid")

    weather_summary: WeatherSummary | None = None
    temp_max_c: Temperature | None = None
    temp_min_c: Temperature | None = None
    rain_mm: Rainfall | None = None
    weather_source: WeatherSource = "manual"


def _blank_to_none(value: str | None) -> str | None:
    return value or None


class ReportCreate(WeatherFields):
    report_date: date
    crew_count: CrewCount
    work_done: WorkDone
    problems: Problems | None = None
    progress: list[ProgressEntry] = Field(default_factory=list, max_length=MAX_PROGRESS_ENTRIES)

    _problems = field_validator("problems")(_blank_to_none)

    @field_validator("progress")
    @classmethod
    def _unique_tasks(cls, value: list[ProgressEntry]) -> list[ProgressEntry]:
        if len({entry.task_id for entry in value}) != len(value):
            raise ValueError("Each task can appear only once.")
        return value


class ReportUpdate(WeatherFields):
    """Corrections on the day of submission. Task progress is not editable here."""

    weather_source: WeatherSource | None = None  # type: ignore[assignment]
    crew_count: CrewCount | None = None
    work_done: WorkDone | None = None
    problems: Problems | None = None

    _problems = field_validator("problems")(_blank_to_none)


class AuthorOut(BaseModel):
    id: uuid.UUID
    full_name: str


class PhotoOut(BaseModel):
    id: uuid.UUID
    caption: str | None
    width: int
    height: int
    size_bytes: int
    created_at: datetime


class ReportProgressOut(BaseModel):
    task_id: uuid.UUID | None
    task_name: str
    percent_before: Decimal
    percent_after: Decimal


class ReportSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    report_date: date
    author: AuthorOut
    weather_summary: str | None
    rain_mm: Decimal | None
    crew_count: int
    work_done_preview: str
    has_problems: bool
    photo_count: int
    progress_count: int
    submitted_at: datetime


class ReportList(BaseModel):
    items: list[ReportSummary]
    total: int


class ReportDetail(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    report_date: date
    author: AuthorOut
    weather_summary: str | None
    temp_max_c: Decimal | None
    temp_min_c: Decimal | None
    rain_mm: Decimal | None
    weather_source: WeatherSource
    crew_count: int
    work_done: str
    problems: str | None
    submitted_at: datetime
    updated_at: datetime
    photos: list[PhotoOut]
    progress: list[ReportProgressOut]
    # Whether the caller may still correct the report or add photos (author, same day).
    editable: bool
    photo_limit: int


class TodayStatus(BaseModel):
    """One active project and whether today's report is in (BR-07)."""

    project_id: uuid.UUID
    project_code: str
    project_name: str
    site_code: str
    report_id: uuid.UUID | None
    submitted_at: datetime | None
    author_name: str | None


class ReportStatus(BaseModel):
    date: date
    deadline: datetime
    deadline_passed: bool
    projects: list[TodayStatus]


class WeatherDayOut(BaseModel):
    date: date
    summary: str
    weather_code: int | None
    temp_max_c: Decimal | None
    temp_min_c: Decimal | None
    rain_mm: Decimal | None
    rain_probability: int | None


class WeatherOut(BaseModel):
    site_code: str
    available: bool
    stale: bool
    fetched_at: datetime | None
    message: str | None
    days: list[WeatherDayOut]
    # BR-06 groundwork: days with heavy rain forecast (more than 10 mm).
    heavy_rain_threshold_mm: Decimal


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int
