"""Supplier on-time estimates and BR-12 critical-path items (Phase 10)."""

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, StrictBool


class ChanceRange(BaseModel):
    """The likely range of an on-time chance (10th to 90th percentile, 0 to 1)."""

    low: float
    high: float


class OnTimeOut(BaseModel):
    supplier_id: uuid.UUID
    supplier_name: str
    chance: float  # 0 to 1: the chance the next order arrives on time
    chance_range: ChanceRange  # always shown with the chance
    based_on: int  # deliveries the estimate rests on: shown with every estimate
    low_data: bool  # fewer than the model's low-data threshold: BR-12 suggestions read as tentative
    below_br12: bool  # under 50%: BR-12 suggests an alternative for critical-path items
    model: str  # in words, e.g. "smoothed on-time rate"
    model_version: str


class OutlookOut(BaseModel):
    """Every active supplier's chance for an order on this project, best first."""

    project_id: uuid.UUID
    expected_delivery: date
    lead_time_days: int
    suppliers: list[OnTimeOut]
    critical_request_ids: list[uuid.UUID]  # approved requests on this project that are critical-path items
    threshold: float  # BR-12: 0.5


class CriticalPathOut(BaseModel):
    request_id: uuid.UUID
    critical: bool  # what counts for BR-12: the override if set, otherwise the programme
    from_programme: bool  # what the programme alone says
    override: bool | None  # the project manager's choice, if any
    reason: str
    can_override: bool
    float_days: int  # the near-critical setting: tasks with this much float or less count


class CriticalPathIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    critical: StrictBool | None  # True / False: the PM's override; None: back to the programme. No "yes".
