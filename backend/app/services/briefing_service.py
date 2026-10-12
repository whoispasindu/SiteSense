"""Today's briefing for one reader (Phase 11): gather the facts, write the bullets, keep them for the day.

``build_facts`` reads the reader's projects (their sites only, BR-03) into ``app.ai.briefing.Facts``,
following what the role may see: risk only with ``risk:read``, cost figures only with ``cost:read``.
With no API key, ``today`` writes the rule-based text fresh on every call (it is free) and stores
nothing. With a key, it returns the stored briefing while its facts are unchanged; otherwise it asks
the language model and falls back to the rule-based text on any failure.

Limits on calls to the model: one answer is reused while the facts are unchanged, a new one is
written at most every 15 minutes even when they change, and after a failure the model is tried
again only after 10 minutes. The rule-based text is free and always current otherwise.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai import briefing as writer
from app.core import clock
from app.core.logging import get_logger
from app.core.permissions import Permission, Role, has_permission
from app.integrations.llm import BriefingLLM, LLMUnavailableError
from app.models import (
    Briefing,
    DailyReport,
    IssueSeverity,
    IssueStatus,
    Project,
    ProjectStatus,
    ReportIssue,
    RiskScore,
    User,
)
from app.schemas.analytics import BriefingBullet, BriefingOut
from app.services import analytics_service, cost_service, network_service, risk_service, schedule_service

log = get_logger(__name__)

BRIEFED_STATUSES = (ProjectStatus.PLANNING.value, ProjectStatus.ACTIVE.value, ProjectStatus.ON_HOLD.value)
MIN_AI_REBUILD = timedelta(minutes=15)
RETRY_AFTER_FAILURE = timedelta(minutes=10)
LABELS = {"ai": "AI-written", "rules": "Rule-based"}
_bullets = TypeAdapter(list[BriefingBullet])


def _range(value: object) -> writer.Range | None:
    if isinstance(value, dict) and "low" in value and "high" in value:
        return writer.Range(low=float(value["low"]), high=float(value["high"]))
    return None


def _week_ago_scores(db: Session, ids: list[uuid.UUID], before: date) -> dict[uuid.UUID, int]:
    """Each project's latest score on or before ``before`` (a week ago)."""
    latest = (
        select(RiskScore.project_id, func.max(RiskScore.score_date).label("d"))
        .where(RiskScore.project_id.in_(ids), RiskScore.score_date <= before)
        .group_by(RiskScore.project_id)
        .subquery()
    )
    rows = db.execute(
        select(RiskScore.project_id, RiskScore.score).join(
            latest, (latest.c.project_id == RiskScore.project_id) & (latest.c.d == RiskScore.score_date)
        )
    ).all()
    return {r[0]: int(r[1]) for r in rows}


def _issues(db: Session, ids: list[uuid.UUID], since: date) -> dict[uuid.UUID, writer.IssueFacts]:
    rows = db.execute(
        select(ReportIssue.project_id, ReportIssue.category, ReportIssue.severity)
        .join(DailyReport, DailyReport.id == ReportIssue.report_id)
        .where(
            ReportIssue.project_id.in_(ids),
            ReportIssue.status == IssueStatus.CONFIRMED.value,
            DailyReport.report_date >= since,
        )
    ).all()
    totals: dict[uuid.UUID, tuple[int, int, dict[str, int]]] = {}
    for project_id, category, severity in rows:
        total, high, by_category = totals.get(project_id, (0, 0, {}))
        by_category[category] = by_category.get(category, 0) + 1
        totals[project_id] = (total + 1, high + (severity == IssueSeverity.HIGH.value), by_category)
    return {
        pid: writer.IssueFacts.model_validate({"total_7d": t, "high_7d": h, "by_category_7d": c})
        for pid, (t, h, c) in totals.items()
    }


def _pour_rain(db: Session, project: Project) -> int:
    if project.status not in network_service.CHECKED_STATUSES:
        return 0
    try:
        return sum(1 for t in network_service.analyse(db, project).tasks if t.rain_days)
    except Exception:  # a programme the network cannot read must not stop the briefing
        log.exception("briefing_pour_check_failed", project=project.code)
        return 0


def _sections_over(db: Session, project: Project) -> int:
    return sum(1 for f in cost_service.forecasts(db, project.id).values() if f.over_alert_line)


def build_facts(db: Session, user: User) -> writer.Facts:
    """The allow-listed facts for this reader. Only numbers, codes, project names and rule words."""
    role = Role(user.role)
    sees_risk = has_permission(role, Permission.RISK_READ)
    sees_cost = has_permission(role, Permission.COST_READ)
    today = clock.site_today()
    scoped = analytics_service.scoped_projects(db, user)
    projects = [p for p in scoped if p.status in BRIEFED_STATUSES]
    ids = [p.id for p in projects]

    ranking = {r.project_id: r for r in risk_service.ranking(db, user)} if sees_risk and ids else {}
    week_ago = _week_ago_scores(db, ids, today - timedelta(days=7)) if ranking else {}
    progress = {s.project.id: s for s in schedule_service.summaries(db, user) if s.task_count > 0}
    filed: set[uuid.UUID] = set()
    if ids:
        on_day = (DailyReport.project_id.in_(ids), DailyReport.report_date == today)
        filed = set(db.scalars(select(DailyReport.project_id).where(*on_day)))
    issues = _issues(db, ids, today - timedelta(days=6)) if ids else {}
    stop_work = analytics_service.open_stop_work(db, ids)
    no_issues = writer.IssueFacts(total_7d=0, high_7d=0, by_category_7d={})

    facts: list[writer.ProjectFacts] = []
    for p in projects:
        r = ranking.get(p.id)
        risk = None
        if r is not None and r.score is not None and r.level is not None:
            ranges = r.ranges.model_dump() if r.ranges else {}
            before = week_ago.get(p.id)
            risk = writer.RiskFacts(
                score=r.score,
                level=r.level,
                score_range=_range(ranges.get("score")),
                change_7d=r.score - before if before is not None else None,
                delay_days=float(r.delay_days or 0),
                delay_range=_range(ranges.get("delay_days")),
                overrun_pct=float(r.overrun_pct or 0) if sees_cost else None,
                overrun_range=_range(ranges.get("overrun_pct")) if sees_cost else None,
            )  # fmt: skip
        s = progress.get(p.id)
        due = p.status == ProjectStatus.ACTIVE.value and p.start_date <= today
        facts.append(
            writer.ProjectFacts(
                code=p.code,
                name=p.name,
                status=p.status,
                risk=risk,
                planned_pct=round(s.planned_percent, 1) if s else None,
                actual_pct=round(s.actual_percent, 1) if s else None,
                report_due_today=due,
                report_filed_today=p.id in filed,
                issues=issues.get(p.id, no_issues),
                stop_work_open=stop_work.get(p.id, 0),
                pour_rain_tasks=_pour_rain(db, p),
                sections_over_budget=_sections_over(db, p) if sees_cost else None,
            )
        )

    queue = analytics_service.approvals(db, user, scoped)
    kinds = [item.kind for item in queue]
    return writer.Facts(
        date=today,
        role=user.role,
        sees_cost=sees_cost,
        projects=facts,
        waiting_for_you=writer.WaitingFacts(
            material_requests=kinds.count("material_request"),
            purchase_orders=kinds.count("purchase_order"),
            claims=kinds.count("claim"),
            variations=kinds.count("variation"),
        ),
    )


def _out(row: Briefing, note: str | None) -> BriefingOut:
    source = "ai" if row.source == "ai" else "rules"
    return BriefingOut(
        date=row.briefing_date,
        source=source,
        label=LABELS[source],
        model=row.model,
        generated_at=row.created_at,
        bullets=_bullets.validate_python(row.bullets),
        note=note,
    )


def _fallback_note(llm: BriefingLLM | None, row: Briefing) -> str | None:
    if llm is not None and row.source == "rules":
        return "The AI briefing is unavailable just now, so this one is written by fixed rules."
    return None


def write(facts: writer.Facts, llm: BriefingLLM | None) -> tuple[str, str | None, list[writer.Bullet]]:
    """(source, model, bullets): the model's answer when it gives a valid one, the rules otherwise."""
    if llm is not None and facts.projects:
        try:
            raw = llm.complete(
                writer.SYSTEM, writer.prompt(facts), writer.output_schema([p.code for p in facts.projects])
            )
            return "ai", llm.model, writer.parse_llm(facts, raw)
        except (LLMUnavailableError, writer.InvalidAnswerError) as exc:
            log.warning("briefing_fell_back", reason=str(exc)[:40] or type(exc).__name__)
    return "rules", None, writer.write_rules(facts)


def today(db: Session, user: User, llm: BriefingLLM | None) -> BriefingOut:
    facts = build_facts(db, user)
    now = clock.utcnow()
    if llm is None:
        # No model: the rule-based text is free, so it is written fresh every time and never stored.
        return BriefingOut(
            date=facts.date,
            source="rules",
            label=LABELS["rules"],
            model=None,
            generated_at=now,
            bullets=_bullets.validate_python([b.model_dump() for b in writer.write_rules(facts)]),
            note=None,
        )
    digest = hashlib.sha256(f"{facts.canonical_json()}|{llm.model}".encode()).hexdigest()
    user_id = user.id
    row = db.scalar(select(Briefing).where(Briefing.user_id == user_id, Briefing.briefing_date == facts.date))
    if row is not None:
        age = now - row.created_at
        unchanged = row.facts_sha256 == digest
        if unchanged and (row.source == "ai" or llm is None or age < RETRY_AFTER_FAILURE):
            return _out(row, _fallback_note(llm, row))
        if llm is not None and row.source == "ai" and age < MIN_AI_REBUILD:
            return _out(row, None)  # the facts moved, but a fresh AI briefing is at most 15 minutes away

    # Release the database connection while the model writes (up to the timeout).
    db.rollback()
    source, model, bullets = write(facts, llm)
    values = {
        "facts_sha256": digest,
        "source": source,
        "model": model,
        "bullets": [b.model_dump() for b in bullets],
        "created_at": now,
    }
    stmt = insert(Briefing).values(id=uuid.uuid4(), user_id=user_id, briefing_date=facts.date, **values)
    db.execute(stmt.on_conflict_do_update(constraint="uq_briefings_user_date", set_=values))
    db.commit()
    stored = db.scalar(
        select(Briefing).where(Briefing.user_id == user_id, Briefing.briefing_date == facts.date)
    )
    assert stored is not None
    log.info("briefing_written", source=source, bullets=len(bullets))
    return _out(stored, _fallback_note(llm, stored))
