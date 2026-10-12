"""Risk forecasts (Phase 6; ranges and SHAP drivers since risk model v2, Phase 10). Every forecast
carries its likely range, its drivers, the gaps in its data and the model version, and is labelled as
an estimate in the UI: people decide, the model suggests."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Level = Literal["low", "medium", "high"]


class DriverOut(BaseModel):
    feature: str
    label: str
    kind: Literal["signal", "context"]
    value: str  # the input in words ("4.0 points behind")
    delay_days: float  # how much this factor moved the delay forecast (SHAP value since v2)
    overrun_pct: float


class RangeOut(BaseModel):
    """The likely range: 8 in 10 outcomes fall inside it (10th to 90th percentile)."""

    low: float
    high: float


class ScoreRange(BaseModel):
    low: int  # the risk score at the low end of the delay and overrun ranges
    high: int  # and at the high end


class Ranges(BaseModel):
    delay_days: RangeOut
    overrun_pct: RangeOut
    score: ScoreRange


class RiskOut(BaseModel):
    score_date: date
    score: int
    level: Level
    delay_days: Decimal  # forecast delay at completion
    overrun_pct: Decimal  # forecast cost overrun at completion
    ranges: Ranges | None  # None only for scores made before risk model v2
    drivers: list[DriverOut]
    notes: list[str]  # inputs that were missing and took neutral values
    model_version: str
    scored_at: datetime


class RiskHistoryPoint(BaseModel):
    date: date
    score: int
    level: Level
    score_range: ScoreRange | None


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
    ranges: Ranges | None
    top_driver: str | None
    score_date: date | None


# --- What-if planner (Phase 10) ----------------------------------------------------------------------

ActionId = Literal["add_crew", "work_sundays", "expedite_materials", "weather_protection"]
Money = Annotated[Decimal, Field(ge=0, le=Decimal("9999999999999.99"), max_digits=15, decimal_places=2)]


class WhatIfActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ActionId
    cost: Money | None = None  # the PM's estimate of what the action costs (LKR); None: not entered


class WhatIfIn(BaseModel):
    """The recovery actions to test together. Nothing is saved: the planner only calculates."""

    model_config = ConfigDict(extra="forbid")

    actions: list[WhatIfActionIn] = Field(default_factory=list, max_length=4)

    @field_validator("actions")
    @classmethod
    def _each_once(cls, actions: list[WhatIfActionIn]) -> list[WhatIfActionIn]:
        if len({a.id for a in actions}) != len(actions):
            raise ValueError("Each action can be chosen once.")
        return actions


class ForecastOut(BaseModel):
    """A forecast with its likely range, always together."""

    delay_days: float
    delay_range: RangeOut
    overrun_pct: float
    overrun_range: RangeOut
    score: int
    score_range: ScoreRange
    level: Level


class EffectOut(BaseModel):
    """How much an action saves (positive: better), from half its planned change to all of it."""

    low: float
    high: float


class WhatIfActionOut(BaseModel):
    id: ActionId
    label: str
    description: str
    change: str  # what it does to the model's inputs, in words
    selected: bool
    delay_saved_days: EffectOut  # simulation estimate
    overrun_saved_pct: EffectOut  # the model's view only: the action's own cost is separate
    cost: Decimal | None  # as entered; None: "cost not entered"
    cost_pct: float | None  # that cost as % of the project's cost budget


class AdviceOut(BaseModel):
    id: str
    label: str
    text: str


class WhatIfOut(BaseModel):
    project_id: uuid.UUID
    as_of: date
    model_version: str
    baseline: ForecastOut
    actions: list[WhatIfActionOut]  # every action in the catalogue, tested on its own
    plan: ForecastOut | None  # the selected actions together, at their planned change, costs included
    plan_delay_saved_days: EffectOut | None
    plan_overrun_saved_pct: EffectOut | None  # the model's saving less the entered costs
    costs_not_entered: list[str]  # selected actions whose cost is blank: never treated as free
    advice: list[AdviceOut]  # management actions: advice only, no forecast change
    notes: list[str]
