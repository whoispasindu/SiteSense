"""The weekly PDF report (Phase 11): the reader's portfolio on one or two pages.

Only for roles that see costs (``cost:read``: project managers and quantity surveyors), because it
carries budgets and forecasts. Built from the same numbers as the dashboard (``analytics_service``)
and the rule-based briefing (never the language model, so the PDF is repeatable). Forecasts show
their likely range. Everything printed from the database is escaped before it reaches ReportLab's
paragraph markup.

Also queues the Monday email (07:00 site time) for those who take it (``alerts.wants_weekly_report``).
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import briefing as writer
from app.core import clock
from app.core.logging import get_logger
from app.core.permissions import ROLE_LABELS, Permission, Role, has_permission
from app.models import EmailOutbox, User
from app.models.alerts import MAX_ATTACHMENT_BYTES
from app.schemas.analytics import Portfolio
from app.services import alerts, analytics_service, briefing_service

log = get_logger(__name__)

INK = colors.HexColor("#1f2933")
SOFT = colors.HexColor("#52606d")
RULE = colors.HexColor("#cbd2d9")
SUNK = colors.HexColor("#f0f2f4")
ACCENT = colors.HexColor("#0b6e99")
HIGH = colors.HexColor("#b42318")


def can_receive(user: User) -> bool:
    return has_permission(Role(user.role), Permission.COST_READ)


def _lkr(value: Decimal | None) -> str:
    if value is None:
        return "-"
    millions = value / Decimal(1_000_000)
    if abs(millions) >= 1000:
        return f"{millions / 1000:,.2f} bn"
    return f"{millions:,.1f} M" if abs(millions) >= 1 else f"{value:,.0f}"


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text), style)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "body", parent=base["BodyText"], fontName="Helvetica", fontSize=9, leading=12, textColor=INK
    )
    return {
        "title": ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=18, leading=22),
        "meta": ParagraphStyle("meta", parent=body, textColor=SOFT),
        "h2": ParagraphStyle(
            "h2",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": body,
        "cell": ParagraphStyle("cell", parent=body, fontSize=8, leading=10),
        "num": ParagraphStyle("num", parent=body, fontSize=8, leading=10, alignment=TA_RIGHT),
        "small": ParagraphStyle("small", parent=body, fontSize=7.5, leading=9.5, textColor=SOFT),
    }


def _table(rows: list[list[Paragraph]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), SUNK),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
                ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def render(portfolio: Portfolio, facts: writer.Facts, role_label: str, generated: datetime) -> bytes:
    """The PDF for one reader."""
    s = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="SiteSense weekly report",
        author="SiteSense",
    )
    monday = portfolio.as_of - timedelta(days=portfolio.as_of.weekday())
    story: list[object] = [
        _p("SiteSense weekly report", s["title"]),
        _p(
            f"Week of {monday:%d %B %Y} · as of {portfolio.as_of:%a %d %b %Y} · for the {role_label} · "
            f"generated {generated.astimezone(clock.SITE_TIME_ZONE):%d %b %Y %H:%M} site time",
            s["meta"],
        ),
        Spacer(1, 6),
    ]

    k = portfolio.kpis
    tiles = [
        ("Active projects", f"{k.active_projects} of {k.total_projects}"),
        (
            "Average progress",
            "-"
            if k.average_actual_pct is None
            else f"{k.average_actual_pct:.1f}% (plan {k.average_planned_pct:.1f}%)",
        ),
        ("Behind plan", str(k.behind_plan)),
        ("High risk (BR-10)", "-" if k.high_risk is None else str(k.high_risk)),
        ("Stop-work open (BR-11)", str(k.stop_work_open)),
        ("Waiting for you", str(k.waiting_for_you)),
    ]
    tile_table = Table(
        [[_p(label, s["small"]) for label, _ in tiles], [_p(value, s["h2"]) for _, value in tiles]],
        colWidths=[44 * mm] * len(tiles),
    )
    tile_table.setStyle(
        TableStyle([("BOX", (0, 0), (-1, -1), 0.5, RULE), ("INNERGRID", (0, 0), (-1, -1), 0.3, RULE)])
    )
    story += [tile_table, Spacer(1, 4)]

    story.append(_p("This week's points", s["h2"]))
    for b in writer.write_rules(facts):
        story.append(_p(f"• {b.text}", s["body"]))

    story.append(_p("Projects", s["h2"]))
    cost = {c.code: c for c in portfolio.cost.projects} if portfolio.cost else {}
    header = [
        "Project",
        "Progress (plan)",
        "Risk score (likely)",
        "Forecast delay (likely)",
        "Budget LKR",
        "Committed LKR",
        "Final at current rates",
        "Risk model final (likely)",
    ]
    rows: list[list[Paragraph]] = [[_p(h, s["cell"] if i == 0 else s["num"]) for i, h in enumerate(header)]]
    for f in sorted(facts.projects, key=lambda f: -(f.risk.score if f.risk else -1)):
        c = cost.get(f.code)
        progress = "-" if f.actual_pct is None else f"{f.actual_pct:.1f}% ({f.planned_pct:.1f}%)"
        score = delay = "-"
        if f.risk is not None:
            sr, dr = f.risk.score_range, f.risk.delay_range
            score = f"{f.risk.score} {f.risk.level}" + (f" ({round(sr.low)}-{round(sr.high)})" if sr else "")
            delay = f"{f.risk.delay_days:.0f} d" + (f" ({round(dr.low)} to {round(dr.high)} d)" if dr else "")
        model = (
            f"{_lkr(c.model_final_range.low)} to {_lkr(c.model_final_range.high)}"
            if c is not None and c.model_final_range is not None
            else "-"
        )
        rows.append(
            [
                _p(f"{f.code} {f.name}", s["cell"]),
                _p(progress, s["num"]),
                _p(score, s["num"]),
                _p(delay, s["num"]),
                _p(_lkr(c.budget) if c else "-", s["num"]),
                _p(_lkr(c.committed) if c else "-", s["num"]),
                _p(_lkr(c.forecast_final) if c else "-", s["num"]),
                _p(model, s["num"]),
            ]
        )
    widths = [70 * mm, 26 * mm, 28 * mm, 34 * mm, 25 * mm, 25 * mm, 30 * mm, 30 * mm]
    story.append(_table(rows, widths) if len(rows) > 1 else _p("No open projects on your sites.", s["body"]))

    story.append(_p("Issues confirmed per week", s["h2"]))
    weeks = portfolio.issue_trend[-4:]
    categories = [c for c in (weeks[0].by_category if weeks else {}) if any(w.by_category[c] for w in weeks)]
    issue_rows = [
        [
            _p("Week of", s["cell"]),
            *(_p(c.replace("_", " ").capitalize(), s["num"]) for c in categories),
            _p("Total", s["num"]),
        ]
    ]
    for w in weeks:
        issue_rows.append(
            [
                _p(f"{w.week_start:%d %b}", s["cell"]),
                *(_p(str(w.by_category[c]), s["num"]) for c in categories),
                _p(str(w.total), s["num"]),
            ]
        )
    story.append(_table(issue_rows, [30 * mm] + [24 * mm] * (len(categories) + 1)))

    story += [
        Spacer(1, 8),
        _p(
            "Ranges are the risk model's likely range. Final at current rates projects each cost section "
            "at its spending rate so far; the risk model's final cost is the budget moved by its forecast "
            "overrun range. A negative delay is days early. Figures cover only the projects on your sites.",
            s["small"],
        ),
    ]
    doc.build(story)  # type: ignore[arg-type]  # flowables
    return buffer.getvalue()


def build_for(db: Session, user: User) -> bytes:
    portfolio = analytics_service.portfolio(db, user)
    facts = briefing_service.build_facts(db, user)
    return render(portfolio, facts, ROLE_LABELS[Role(user.role)], clock.utcnow())


def filename(on: date) -> str:
    return f"sitesense-weekly-{on}.pdf"


def queue_weekly(db: Session) -> int:
    """The Monday email: each active PM (unless opted out) and QS (if opted in) gets their PDF. Commits.

    Idempotent within the week: a second run does not queue a second copy.
    """
    now = clock.utcnow()
    today = clock.site_today()
    week_start = datetime.combine(
        today - timedelta(days=today.weekday()), datetime.min.time(), clock.SITE_TIME_ZONE
    )
    queued = 0
    for user in db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.email)).all():
        if not can_receive(user) or not alerts.wants_weekly_report(user, alerts.preferences(db, user.id)):
            continue
        already = db.scalar(
            select(EmailOutbox.id).where(
                EmailOutbox.user_id == user.id,
                EmailOutbox.kind == "weekly_report",
                EmailOutbox.created_at >= week_start,
            )
        )
        if already is not None:
            continue
        try:
            pdf = build_for(db, user)
        except Exception:
            db.rollback()
            log.exception("weekly_report_failed", user_id=str(user.id))
            continue
        if len(pdf) > MAX_ATTACHMENT_BYTES:
            log.warning("weekly_report_too_large", user_id=str(user.id), size=len(pdf))
            continue
        subject, body = alerts.weekly_email()
        db.add(
            EmailOutbox(
                user_id=user.id,
                kind="weekly_report",
                subject=subject,
                body=body,
                attachment_name=filename(today),
                attachment=pdf,
                created_at=now,
            )
        )
        db.commit()
        queued += 1
    return queued
