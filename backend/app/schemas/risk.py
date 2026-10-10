"""Risk forecasts (Phase 6). Every forecast carries its drivers, the gaps in its data and the model
version, and is labelled as an estimate in the UI: people decide, the model suggests."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

Level = Literal["low", "medium", "high"]


class DriverOut(BaseModel):
    feature: str
    label: str
    kind: Literal["signal", "context"]
    value: str  # the input in words ("4.0 points behind")
    delay_days: float  # how much this factor moved the delay forecast (approximate)
    overrun_pct: float


class RiskOut(BaseModel):
    score_date: date
    score: int
    level: Level
    delay_days: Decimal  # forecast delay at completion
    overrun_pct: Decimal  # forecast cost overrun at completion
    drivers: list[DriverOut]
    notes: list[str]  # inputs that were missing and took neutral values
    model_version: str
    scored_at: datetime


class RiskHistoryPoint(BaseModel):
    date: date
    score: int
    level: Level


class ProjectRisk(BaseModel):
    project_id: uuid.UUID
    latest: RiskOut | None  # None until the project has been scored
    history: list[RiskHistoryPoint]  # the last 14 days


class RiskRanking(BaseModel):
    project_id: uuid.UUID
    code: str
    name: str
    site_code: str
    status: str
    score: int | None
    level: Level | None
    delay_days: Decimal | None
    overrun_pct: Decimal | None
    top_driver: str | None
    score_date: date | None
