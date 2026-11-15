"""The dashboard (Phase 11): portfolio analytics, the daily briefing and email preferences.

Sections a role may not see are ``None``, not empty: cost figures only for ``cost:read`` (PM, QS),
risk only for ``risk:read``. The client never reaches these endpoints.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

from app.schemas.portal import HandoverReminderItem
from app.schemas.report import WeatherDayOut
from app.schemas.risk import RiskRanking

ApprovalKind = Literal["material_request", "purchase_order", "claim", "variation"]


class Kpis(BaseModel):
    active_projects: int
    total_projects: int
    average_actual_pct: float | None  # across projects with a programme; None when none has one
    average_planned_pct: float | None
    behind_plan: int  # more than 2 points behind plan
    reports_due_today: int  # active projects on the user's sites
    reports_filed_today: int
    issues_this_week: int  # confirmed issues in reports since Monday
    stop_work_open: int  # BR-11 flags waiting for the project manager
    waiting_for_you: int  # the approval queue
    high_risk: int | None  # BR-10; None without risk:read


class CostTotalsOut(BaseModel):
    budget: Decimal
    committed: Decimal
    forecast_final: Decimal
    over_budget: int


class RangeMoney(BaseModel):
    low: Decimal
    high: Decimal


class ProjectCostPoint(BaseModel):
    project_id: uuid.UUID
    code: str
    name: str
    budget: Decimal
    committed: Decimal
    forecast_final: Decimal  # at current rates (the cost rules, Phase 8)
    model_final_range: RangeMoney | None  # the risk model's likely final cost; None until scored with ranges


class CostAgainstPlan(BaseModel):
    totals: CostTotalsOut
    projects: list[ProjectCostPoint]


class IssueWeek(BaseModel):
    week_start: date
    total: int
    by_category: dict[str, int]


class SiteWeather(BaseModel):
    site_code: str
    site_name: str
    available: bool
    stale: bool  # the saved forecast is older than a day: the morning refresh failed
    fetched_at: datetime | None
    days: list[WeatherDayOut]
    heavy_rain_threshold_mm: Decimal


class ApprovalItem(BaseModel):
    kind: ApprovalKind
    id: uuid.UUID
    number: str
    project_id: uuid.UUID
    project_code: str
    title: str
    status: str
    since: datetime
    link: str


class Portfolio(BaseModel):
    as_of: date
    kpis: Kpis
    cost: CostAgainstPlan | None  # None without cost:read
    risk: list[RiskRanking] | None  # None without risk:read
    issue_trend: list[IssueWeek]  # the last 8 weeks, oldest first
    weather: list[SiteWeather]
    approvals: list[ApprovalItem]  # oldest first
    # Phase 12: published handover dates that look out of date (project managers only, else None).
    handover_reminders: list[HandoverReminderItem] | None = None


# --- The daily briefing ---------------------------------------------------------------------------------

SourceKind = Literal["risk", "programme", "reports", "issues", "stop_work", "weather", "approvals", "cost"]


class BriefingSource(BaseModel):
    kind: SourceKind
    count: int  # how many records the bullet rests on, counted by the server (never by the model)


class BriefingBullet(BaseModel):
    text: str
    projects: list[str]  # project codes
    sources: list[BriefingSource]


class BriefingOut(BaseModel):
    date: date
    source: Literal["ai", "rules"]
    label: str  # "AI-written" or "Rule-based"
    model: str | None
    generated_at: datetime
    bullets: list[BriefingBullet]
    note: str | None  # why the rule-based text is shown, when an AI briefing was expected


# --- Email preferences ----------------------------------------------------------------------------------


class NotificationPreferencesOut(BaseModel):
    email_urgent: bool
    email_digest: bool
    weekly_report: bool  # the effective choice (the role's default when not set)
    weekly_report_available: bool  # only roles that see costs (PM, QS) can get the PDF
    stop_work_always: bool  # stop-work emails cannot be turned off
    email_configured: bool  # False: emails are written to the server log, not sent
    digest_time: str  # "18:30", site time
    weekly_time: str  # "Monday 07:00", site time


class NotificationPreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_urgent: StrictBool
    email_digest: StrictBool
    weekly_report: StrictBool | None = None  # ignored (and must be absent or false) for other roles
