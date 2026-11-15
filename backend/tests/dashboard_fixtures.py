"""Shared fixtures for the Phase 11 tests: one busy project with everything the dashboard reads.

Every piece of free text and every person's name in it is distinctive (``SECRETS``), so the leak
tests can check that none of it reaches the language model or an email.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import clock
from app.core.permissions import Role
from app.models import (
    Approval,
    BoqItem,
    BoqSection,
    BudgetLine,
    DailyReport,
    MaterialRequest,
    Notification,
    Project,
    ReportAction,
    ReportIssue,
    RiskScore,
    Site,
    Supplier,
    Task,
    User,
    VariationOrder,
    WeatherForecast,
)
from tests.conftest import bearer, login

PEOPLE = {
    Role.PROJECT_MANAGER: "Zephyrine Quillfeather",
    Role.SITE_ENGINEER: "Bartholomew Nkemelu",
    Role.QUANTITY_SURVEYOR: "Ottoline Varga",
    Role.PROCUREMENT_OFFICER: "Ignatius Fairweather",
}
SECRETS = [
    *PEOPLE.values(),
    "Quillfeather",
    "Nkemelu",
    "SECRET-WORKDONE",
    "SECRET-PROBLEMS",
    "SECRET-SNIPPET",
    "SECRET-ACTION",
    "SECRET-NOTES",
    "SECRET-COMMENT",
    "SECRET-VARIATION-TITLE",
    "SECRET-VARIATION-DESC",
    "SECRET-SUPPLIER",
    "SECRET-TASK",
    "SECRET-SITE",
    "SECRET-CLIENT",
    "SECRET-BOQ-ITEM",
    "SECRET-DRIVER",
    "SECRET-NOTIFICATION",
    "@sitesense.example",
]


@dataclass(frozen=True)
class Member:
    user: User
    headers: dict[str, str]


@dataclass(frozen=True)
class World:
    today: date
    site: Site
    project: Project
    other_project: Project  # on a site nobody here is assigned to
    task: Task
    request: MaterialRequest
    variation: VariationOrder
    pm: Member
    se: Member
    qs: Member
    buyer: Member


def at(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=clock.site_zone()).astimezone(UTC)


@pytest.fixture
def world(
    api: TestClient, db: Session, make_site: Callable[..., Site], make_user: Callable[..., User]
) -> World:
    today = clock.site_today()
    site = make_site("COL-11")
    site.name, site.latitude, site.longitude = "SECRET-SITE Wellawatte yard", 6.87, 79.86
    other_site = make_site("KDY-02")
    db.commit()

    project = Project(
        code="HR-1", name="Havelock Residences", site_id=site.id, client_name="SECRET-CLIENT Holdings",
        project_type="residential", status="active", contract_value=Decimal("10000000.00"),
        start_date=today - timedelta(days=200), planned_end=today + timedelta(days=300),
    )  # fmt: skip
    other = Project(
        code="KD-9", name="Kandy Offices", site_id=other_site.id, client_name="Other",
        project_type="commercial", status="active", contract_value=Decimal("5000000.00"),
        start_date=today - timedelta(days=30), planned_end=today + timedelta(days=400),
    )  # fmt: skip
    db.add_all([project, other])
    db.flush()

    members: dict[Role, Member] = {}
    for role, name in PEOPLE.items():
        user = make_user(role, sites=[] if role == Role.PROCUREMENT_OFFICER else [site])
        user.full_name = name
        db.commit()
        members[role] = Member(user, bearer(login(api, user.email)))
    pm, se, qs = members[Role.PROJECT_MANAGER], members[Role.SITE_ENGINEER], members[Role.QUANTITY_SURVEYOR]

    section = BoqSection(project_id=project.id, code="A", name="Structure", position=1)
    db.add(section)
    db.flush()
    item = BoqItem(
        project_id=project.id, section_id=section.id, item_code="A.1", description="SECRET-BOQ-ITEM cement",
        unit="bag", quantity=Decimal("1000"), rate=Decimal("2500"), amount=Decimal("2500000.00"), position=1,
    )  # fmt: skip
    db.add_all(
        [item, BudgetLine(project_id=project.id, section_id=section.id, budget_amount=Decimal("2000000.00"))]
    )
    task = Task(
        project_id=project.id, code="T-010", name="SECRET-TASK frame level 4",
        planned_start=today - timedelta(days=100), planned_end=today + timedelta(days=100),
        weight=Decimal("100"), percent_complete=Decimal("20.00"), position=1, boq_section_id=section.id,
        is_concrete_pour=True,
    )  # fmt: skip
    db.add(task)
    db.flush()

    report = DailyReport(
        project_id=project.id, author_id=se.user.id, report_date=today, crew_count=12,
        work_done="SECRET-WORKDONE Bartholomew Nkemelu fixed the formwork.",
        problems="SECRET-PROBLEMS Zephyrine Quillfeather was told about the crack.", submitted_at=at(today),
    )  # fmt: skip
    db.add(report)
    db.flush()
    db.add_all(
        [
            ReportIssue(
                report_id=report.id, project_id=project.id, snippet="SECRET-SNIPPET a worker slipped",
                category="safety", severity="high", status="confirmed", source="manual", position=1,
                created_at=at(today), confirmed_by=se.user.id, confirmed_at=at(today),
            ),
            ReportIssue(
                report_id=report.id, project_id=project.id, snippet="SECRET-SNIPPET cement late",
                category="material_delay", severity="medium", status="confirmed", source="ai", position=2,
                created_at=at(today), confirmed_by=se.user.id, confirmed_at=at(today),
            ),
            ReportIssue(
                report_id=report.id, project_id=project.id, snippet="SECRET-SNIPPET removed one",
                category="labour", severity="low", status="removed", source="ai", position=3,
                created_at=at(today),
            ),
            ReportAction(
                report_id=report.id, project_id=project.id, kind="stop_work", status="open",
                summary="SECRET-ACTION stop work on the scaffold", created_by=se.user.id,
                created_at=at(today),
                stop_scope="project",
            ),
        ]
    )  # fmt: skip

    request = MaterialRequest(
        number="MR-9001", project_id=project.id, boq_item_id=item.id, requested_by=se.user.id,
        quantity=Decimal("400"), unit_price=Decimal("2600"), needed_by=today + timedelta(days=10),
        notes="SECRET-NOTES for the slab", status="pm_approval", approval_level="pm",
        submitted_at=at(today, 8),
    )  # fmt: skip
    db.add(request)
    db.flush()
    db.add(
        Approval(
            request_id=request.id, actor_id=qs.user.id, action="approve", from_status="requested",
            to_status="pm_approval", comment="SECRET-COMMENT checked", created_at=at(today, 8),
        )
    )  # fmt: skip
    variation = VariationOrder(
        number="VO-9001", project_id=project.id, title="SECRET-VARIATION-TITLE extra balcony",
        description="SECRET-VARIATION-DESC as asked", section_id=section.id, time_impact_days=5,
        status="awaiting_pricing", raised_by=pm.user.id, raised_by_role="pm",
        raised_at=at(today - timedelta(days=1)),
    )  # fmt: skip
    db.add(variation)
    db.add(Supplier(name="SECRET-SUPPLIER Lanka", contact_name="Nimal", phone="+94 11 000 0000"))

    ranges = {
        "delay_days": {"low": 10.2, "high": 27.4},
        "overrun_pct": {"low": 1.5, "high": 9.0},
        "score": {"low": 71, "high": 84},
    }
    driver = {
        "feature": "progress_gap_pct", "label": "SECRET-DRIVER progress gap", "kind": "signal",
        "value": "4.0 points behind", "delay_days": 6.0, "overrun_pct": 1.0,
    }  # fmt: skip
    for day, score, level in ((today, 78, "high"), (today - timedelta(days=7), 60, "medium")):
        db.add(
            RiskScore(
                project_id=project.id, score_date=day, score=score, level=level, delay_days=Decimal("18.0"),
                overrun_pct=Decimal("6.50"), ranges=ranges, drivers=[driver], features={"notes": []},
                model_version="2.0.0", created_at=at(day, 6),
            )
        )  # fmt: skip
    db.add(
        Notification(
            user_id=pm.user.id, kind="report_submitted", title="Daily report filed for HR-1",
            body="SECRET-NOTIFICATION Bartholomew Nkemelu filed it", link=f"/reports/{report.id}",
            project_id=project.id, created_at=at(today, 10),
        )
    )  # fmt: skip
    for i in range(5):
        db.add(
            WeatherForecast(
                site_id=site.id, forecast_date=today + timedelta(days=i), weather_code=61, summary="Rain",
                temp_max_c=Decimal("30.0"), temp_min_c=Decimal("24.0"),
                rain_mm=Decimal("14.0" if i else "1.0"),
                rain_probability=70, fetched_at=clock.utcnow(),
            )
        )  # fmt: skip
    db.commit()
    return World(
        today=today, site=site, project=project, other_project=other, task=task, request=request,
        variation=variation, pm=pm, se=se, qs=qs, buyer=members[Role.PROCUREMENT_OFFICER],
    )  # fmt: skip
