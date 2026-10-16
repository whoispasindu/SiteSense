"""The dashboard (Phase 11): portfolio analytics, today's briefing, the weekly PDF and email choices.

- ``GET /analytics/portfolio`` and ``GET /briefing/today``: anyone who reads projects, on their own
  sites. Cost sections only for ``cost:read``, risk only for ``risk:read``.
- ``GET /reports/weekly.pdf``: cost roles only (PM, QS), because the PDF carries budgets. Audited.
- ``GET`` and ``PUT /me/notification-preferences``: every signed-in user, for themselves only.

This router is mounted before the reports router, so ``/reports/weekly.pdf`` is not read as a report ID.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import CurrentUser, DbSession, Meta, rate_limit, require_permission
from app.core import clock
from app.core.permissions import Permission
from app.integrations.llm import BriefingLLM
from app.models import User
from app.schemas.analytics import (
    BriefingOut,
    NotificationPreferencesIn,
    NotificationPreferencesOut,
    Portfolio,
)
from app.services import alerts, analytics_service, audit, briefing_service, weekly_report

router = APIRouter(tags=["dashboard"])

ProjectReader = Annotated[User, Depends(require_permission(Permission.PROJECTS_READ))]
CostReader = Annotated[User, Depends(require_permission(Permission.COST_READ))]


def _briefing_llm(request: Request) -> BriefingLLM | None:
    llm: BriefingLLM | None = getattr(request.app.state, "briefing_llm", None)
    return llm


@router.get("/analytics/portfolio", response_model=Portfolio)
def portfolio(user: ProjectReader, db: DbSession) -> Portfolio:
    """KPIs, cost against plan, the risk ranking, issue trends, site weather and the approval queue."""
    return analytics_service.portfolio(db, user)


@router.get("/briefing/today", response_model=BriefingOut)
def briefing_today(
    user: ProjectReader, db: DbSession, llm: Annotated[BriefingLLM | None, Depends(_briefing_llm)]
) -> BriefingOut:
    """3 to 5 bullets on what needs attention today, labelled AI-written or rule-based."""
    return briefing_service.today(db, user, llm)


@router.get(
    "/reports/weekly.pdf",
    response_class=Response,
    dependencies=[Depends(rate_limit("heavy", "heavy_rate_per_minute", per_user=True))],
    responses={200: {"content": {"application/pdf": {}}, "description": "The weekly report as a PDF."}},
)
def weekly_pdf(user: CostReader, db: DbSession, meta: Meta) -> Response:
    pdf = weekly_report.build_for(db, user)
    audit.record(
        db,
        audit.AuditAction.WEEKLY_REPORT_DOWNLOADED,
        meta=meta,
        actor_id=user.id,
        details={"bytes": len(pdf)},
    )
    db.commit()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{weekly_report.filename(clock.site_today())}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/me/notification-preferences", response_model=NotificationPreferencesOut)
def get_preferences(user: CurrentUser, db: DbSession) -> NotificationPreferencesOut:
    return alerts.preferences_out(db, user)


@router.put("/me/notification-preferences", response_model=NotificationPreferencesOut)
def put_preferences(
    data: NotificationPreferencesIn, user: CurrentUser, db: DbSession, meta: Meta
) -> NotificationPreferencesOut:
    """Urgent emails and the evening digest can be turned off; stop-work emails (BR-11) cannot."""
    return alerts.update_preferences(db, user, data, meta=meta)
