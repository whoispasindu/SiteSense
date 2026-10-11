"""Report issues and follow-up actions (Phase 7)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models import ActionKind, ActionStatus, IssueCategory, IssueSeverity, IssueStatus


class IssueOut(BaseModel):
    id: uuid.UUID
    snippet: str  # names redacted
    category: IssueCategory
    severity: IssueSeverity
    status: IssueStatus
    source: Literal["ai", "manual"]
    confidence: float | None  # the model's category probability; None for tags added by hand
    low_confidence: bool
    ai_category: IssueCategory | None
    ai_severity: IssueSeverity | None
    edited: bool  # the author changed the AI's category or severity
    confirmed_at: datetime | None


class ActionOut(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    kind: ActionKind
    status: ActionStatus
    summary: str
    created_at: datetime
    closed_at: datetime | None
    request_id: uuid.UUID | None
    can_close: bool
    # BR-11: for stop-work flags, what they stop.
    stop_scope: Literal["tasks", "project"] | None = None
    stop_task_ids: list[uuid.UUID] = Field(default_factory=list)
    can_edit_scope: bool = False  # the PM, while the flag is open


class ReportIssues(BaseModel):
    report_id: uuid.UUID
    confirmed: bool  # the author has confirmed the tags (then they cannot be analysed again)
    can_confirm: bool  # the caller is the author, on the day, and has not confirmed yet
    model_version: str | None
    low_confidence_below: float
    issues: list[IssueOut]
    actions: list[ActionOut]


Snippet = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]


class ConfirmedIssueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An AI suggestion to keep (category and severity may be changed); omit to add a tag by hand.
    suggestion_id: uuid.UUID | None = None
    category: IssueCategory
    severity: IssueSeverity
    snippet: Snippet | None = None  # required for a tag added by hand

    @model_validator(mode="after")
    def _manual_needs_text(self) -> "ConfirmedIssueIn":
        if self.suggestion_id is None and not self.snippet:
            raise ValueError("A tag added by hand needs the text it is about.")
        return self


class ActionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_request: bool = False  # draft a material request (needs a material delay)
    pm_alert: bool = False  # alert the project managers (needs a high-severity issue)
    stop_work: bool = False  # flag stop-work (needs a safety issue; BR-11)
    # Phase 9: what the stop-work flag stops: chosen tasks (at least one), or the whole project.
    stop_work_scope: Literal["tasks", "project"] = "tasks"
    stop_work_task_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issues: list[ConfirmedIssueIn] = Field(default_factory=list, max_length=30)
    actions: ActionsIn = Field(default_factory=ActionsIn)


class CloseActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Literal["done", "dismissed"]


class StopScopeIn(BaseModel):
    """The PM changes what an open stop-work flag stops (BR-11)."""

    model_config = ConfigDict(extra="forbid")

    scope: Literal["tasks", "project"]
    task_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
