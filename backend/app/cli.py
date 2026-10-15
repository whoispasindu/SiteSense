"""Operator commands.

    python -m app.cli create-admin --email admin@company.lk --name "Nimal Perera"
    python -m app.cli seed-dev            # local development only
    python -m app.cli send-reminders      # missing daily report reminders now (BR-07)
    python -m app.cli refresh-weather     # fetch the 14-day forecast for every active site
    python -m app.cli score-risk          # score every open project's risk now
    python -m app.cli check-variance      # forecast final cost per section; alert new overruns
    python -m app.cli check-pours         # BR-06: alert PMs about pours on heavy-rain days

``create-admin`` prints a one-time temporary password; the admin must change it at first sign-in.
``seed-dev`` creates demo sites and one account per role using SITESENSE_DEMO_PASSWORD, and
refuses to run in production.
"""

import argparse
import io
import os
import sys
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.nlp.tagger import tag_problems
from app.core import clock
from app.core.config import get_settings
from app.core.database import Database
from app.core.permissions import Role
from app.core.scheduler import (
    refresh_weather,
    run_pour_check,
    run_report_reminders,
    run_risk_scoring,
    run_variance_check,
)
from app.core.security import (
    PasswordPolicyError,
    generate_temporary_password,
    hash_password,
    validate_password,
)
from app.integrations.storage import LocalStorage
from app.integrations.weather import OpenMeteoClient
from app.models import (
    BoqItem,
    BoqSection,
    DailyReport,
    Delivery,
    HandoverPublication,
    MaterialRequest,
    ProgressClaim,
    ProgressSnapshot,
    Project,
    PurchaseOrder,
    PurchaseOrderLine,
    ReportIssue,
    ReportPhoto,
    Site,
    Supplier,
    Task,
    TaskDependency,
    User,
)
from app.schemas.contract import (
    ClaimDecisionIn,
    ClaimIn,
    ClaimPaymentIn,
    ClaimSectionIn,
    VariationDecisionIn,
    VariationIn,
)
from app.schemas.materials import DecisionIn, DeliveryIn, OrderLineIn, PurchaseOrderCreate, RequestCreate
from app.schemas.portal import HandoverIn, PhotosShareIn
from app.services import (
    audit,
    claim_service,
    cost_service,
    handover_service,
    materials_service,
    photos,
    portal_service,
    procurement_service,
    report_service,
    risk_service,
    variation_service,
)
from app.services.audit import RequestMeta
from app.services.auth_service import normalize_email
from app.services.boq_import import parse_boq
from app.services.progress import TaskPlan, actual_percent, planned_fraction, week_dates
from app.services.project_service import import_boq

# Recent daily reports for Havelock (days ago, crew, weather, rain mm, work done, problems).
DEMO_REPORTS: list[tuple[int, int, str, Decimal, str, str | None]] = [
    (1, 46, "Light rain", Decimal("6.2"),
     "Level 4 slab: fixed bottom reinforcement on grids A-D and started edge formwork. "
     "Blockwork on level 2 continued on the east side.",
     "Cement delivery from the supplier did not arrive again; blockwork crew short of mortar after 2 pm."),
    (2, 51, "Partly cloudy", Decimal("0.0"),
     "Poured level 3 columns C1-C8 (14 m3). Started scaffolding for the level 4 slab soffit.", None),
    (3, 38, "Heavy rain", Decimal("24.5"),
     "Rain stopped concrete work from 10 am. Crew moved to rebar cutting and bending in the yard.",
     "Heavy rain: level 3 column pour postponed to tomorrow. Site drains overflowing near gate 2."),
    (4, 49, "Mainly clear", Decimal("0.0"),
     "Level 3 slab curing. Blockwork on level 1 completed; plastering crew mobilised to level 1.", None),
    (5, 44, "Light showers", Decimal("3.1"),
     "Stripped level 2 formwork. MEP sleeves installed in level 3 slab before inspection.",
     "Tower crane down for two hours (hydraulic leak); lifts delayed."),
]  # fmt: skip

DEMO_SUPPLIERS = [
    ("Kelani Building Supplies", "Nimal Fernando", "+94 11 245 7781", "cement, blocks, aggregates"),
    ("Southern Steel Traders", "Ruwani de Silva", "+94 91 223 4410", "reinforcement steel"),
    ("Colombo Ready-Mix", "Asanka Perera", "+94 11 287 9002", "ready-mix concrete"),
    ("Ceylon Formwork Hire", "Dinesh Jayasuriya", "+94 11 260 1188", "formwork, scaffolding"),
    ("Hill Country Hardware", "Fathima Rizvi", "+94 81 222 6091", "waterproofing, plaster, hardware"),
]

# Supplier records for BR-12 (Phase 10): (supplier, BOQ item, orders, of which on time), delivered over the
# past year to a finished job. One supplier is weak (under 50%), one has too few deliveries to judge.
DEMO_HISTORY_PROJECT = ("NGR-2025-04", "Negombo Road Warehouse", "Lanka Logistics (Pvt) Ltd")
DEMO_SUPPLIER_HISTORY = [
    ("Kelani Building Supplies", ("B.01", "Cement, 50 kg bags", "bag", "2300"), 14, 12),
    ("Southern Steel Traders", ("B.02", "Reinforcement steel", "kg", "330"), 10, 7),
    ("Colombo Ready-Mix", ("B.03", "Ready-mix concrete, grade 25", "m3", "28500"), 12, 11),
    ("Ceylon Formwork Hire", ("B.04", "Formwork hire", "m2", "950"), 9, 3),
    ("Hill Country Hardware", ("B.05", "Waterproofing membrane", "m2", "1850"), 3, 2),
]

# Havelock material requests and how far each gets:
# (item, quantity, unit price, needed in days, stage, supplier, delivered quantity)
DEMO_REQUESTS: list[tuple[str, str, str, int, str, str | None, str | None]] = [
    ("C.03", "24000", "340", 5, "delivered", "Southern Steel Traders", "24000"),
    ("C.02", "180", "34500", 7, "ordered", "Colombo Ready-Mix", "60"),
    ("D.01", "1200", "2750", 12, "approved", None, None),
    ("C.04", "2000", "2240", 10, "pm_approval", None, None),
    ("B.05", "400", "2600", 9, "requested", None, None),
    ("D.03", "3000", "1200", 20, "change_requested", None, None),
]

# Planned average crews (a risk model input) and the extra history the model reads (Phase 6).
DEMO_CREWS = {"HR-2026-01": 55, "PRO-2026-02": 40, "FVA-2026-03": 45}
# Havelock: two more weeks of reports, crews short of plan and three working days with no report.
HR_EARLIER_REPORTS = {8: 44, 10: 41, 11: 43, 13: 39, 14: 42, 15: 45, 17: 40, 18: 38, 19: 44, 20: 41}
WORKS = [
    "Blockwork and plastering on the lower floors; formwork for the next slab.",
    "Rebar fixing for the slab; scaffolding moved up one level.",
    "Concrete pour for columns; curing of yesterday's slab section.",
]

DEMO_SITES = [
    ("COL-07", "Havelock Residences", "Colombo 05", 6.8836, 79.8650),
    ("KDY-02", "Peradeniya Road Offices", "Kandy", 7.2735, 80.6127),
    ("GAL-11", "Fort View Apartments", "Galle", 6.0329, 80.2168),
    # The finished job behind the supplier history (Phase 10), on its own site: another client's
    # project never shares a site with Havelock's, and clients are linked to projects anyway (Phase 12).
    ("NEG-04", "Negombo Road Warehouse", "Negombo", 7.2008, 79.8737),
]

SEED_DATA = Path(__file__).parent / "seed_data"

# (code, name, site, client, type, status, contract value, start, planned end, BOQ file)
DEMO_PROJECTS = [
    ("HR-2026-01", "Havelock Residences", "COL-07", "Havelock Developers (Pvt) Ltd", "residential", "active",
     Decimal("1114000000.00"), date(2026, 3, 2), date(2027, 9, 30), "boq-havelock-residences.csv"),
    ("PRO-2026-02", "Peradeniya Road Offices", "KDY-02", "Hill Country Holdings PLC", "commercial", "active",
     Decimal("685000000.00"), date(2026, 5, 4), date(2027, 6, 30), None),
    ("FVA-2026-03", "Fort View Apartments", "GAL-11", "Southern Coast Homes", "residential", "planning",
     Decimal("742500000.00"), date(2026, 11, 2), date(2028, 3, 31), None),
]  # fmt: skip

# (code, name, BOQ section, planned start, planned end, weight %): weights follow BOQ section shares.
DEMO_PROGRAMMES: dict[str, list[tuple[str, str, str | None, date, date, Decimal]]] = {
    "HR-2026-01": [
        (
            "T-010",
            "Site establishment and hoarding",
            "A",
            date(2026, 3, 2),
            date(2026, 3, 27),
            Decimal("2.90"),
        ),
        ("T-020", "Piling and pile caps", "B", date(2026, 3, 16), date(2026, 5, 29), Decimal("5.70")),
        ("T-030", "Basement and ground beams", "B", date(2026, 5, 4), date(2026, 6, 26), Decimal("2.50")),
        ("T-040", "Frame: ground to level 4", "C", date(2026, 6, 15), date(2026, 10, 30), Decimal("17.10")),
        ("T-050", "Frame: level 5 to roof", "C", date(2026, 10, 19), date(2027, 2, 26), Decimal("17.10")),
        ("T-060", "Blockwork and plaster", "D", date(2026, 9, 7), date(2027, 4, 30), Decimal("12.00")),
        ("T-070", "Roof waterproofing", "E", date(2027, 2, 15), date(2027, 3, 31), Decimal("1.40")),
        ("T-080", "MEP first fix", "G", date(2026, 10, 5), date(2027, 4, 30), Decimal("7.00")),
        ("T-090", "Finishes and joinery", "F", date(2027, 1, 18), date(2027, 8, 27), Decimal("25.70")),
        (
            "T-100",
            "MEP second fix, lifts and testing",
            "G",
            date(2027, 4, 5),
            date(2027, 9, 10),
            Decimal("6.70"),
        ),
        ("T-110", "External works and handover", "H", date(2027, 6, 1), date(2027, 9, 30), Decimal("1.90")),
    ],
    "PRO-2026-02": [
        ("T-010", "Mobilisation", None, date(2026, 5, 4), date(2026, 5, 29), Decimal("4.00")),
        ("T-020", "Foundations", None, date(2026, 5, 25), date(2026, 8, 14), Decimal("16.00")),
        ("T-030", "Structural frame", None, date(2026, 8, 3), date(2027, 1, 29), Decimal("38.00")),
        ("T-040", "Envelope and services", None, date(2026, 12, 1), date(2027, 5, 14), Decimal("27.00")),
        ("T-050", "Fit-out and handover", None, date(2027, 3, 1), date(2027, 6, 30), Decimal("15.00")),
    ],
}
# How far actual progress sits from plan in the demo (1.0 = exactly on plan).
DEMO_PACE = {"HR-2026-01": 0.84, "PRO-2026-02": 1.06}
# Concrete pours (BR-06) and finish-to-start links (predecessor, successor, lag in working days). Only
# links the planned dates already satisfy: overlapping tasks are left unlinked.
DEMO_POURS = {"HR-2026-01": {"T-020", "T-030", "T-040", "T-050"}, "PRO-2026-02": {"T-020", "T-030"}}
DEMO_LINKS = {
    "HR-2026-01": [
        ("T-010", "T-030", 0),
        ("T-020", "T-040", 5),
        ("T-050", "T-100", 0),
        ("T-070", "T-100", 0),
        ("T-060", "T-110", 0),
    ],
    "PRO-2026-02": [("T-010", "T-030", 0), ("T-020", "T-040", 0), ("T-030", "T-050", 0)],
}

DEMO_USERS = [
    ("admin@sitesense.example", "Dilani Admin", Role.ADMIN, []),
    ("pm@sitesense.example", "Ruwan Project Manager", Role.PROJECT_MANAGER, ["COL-07", "KDY-02"]),
    ("qs@sitesense.example", "Shalini Quantity Surveyor", Role.QUANTITY_SURVEYOR, ["COL-07", "KDY-02"]),
    ("engineer@sitesense.example", "Kasun Site Engineer", Role.SITE_ENGINEER, ["COL-07"]),
    ("procurement@sitesense.example", "Fathima Procurement", Role.PROCUREMENT_OFFICER, []),
    ("client@sitesense.example", "Mr. Jayawardena (Client)", Role.CLIENT, ["COL-07"]),
]


def create_admin(email: str, name: str) -> int:
    settings = get_settings()
    database = Database(settings)
    with database.session_factory() as db:
        normalized = normalize_email(email)
        if db.scalar(select(User).where(User.email == normalized)):
            print(f"A user with email {normalized} already exists.", file=sys.stderr)
            return 1
        temporary = generate_temporary_password()
        user = User(
            email=normalized,
            full_name=name,
            role=Role.ADMIN.value,
            password_hash=hash_password(temporary),
            must_change_password=True,
        )
        db.add(user)
        db.flush()
        audit.record(db, audit.AuditAction.USER_CREATED, target_type="user", target_id=user.id,
                     details={"role": "admin", "via": "cli"})  # fmt: skip
        db.commit()
    database.dispose()
    print(f"Admin created: {normalized}")
    print(f"Temporary password (shown once, must be changed at first sign-in): {temporary}")
    return 0


def seed_dev() -> int:
    settings = get_settings()
    if settings.is_production:
        print("seed-dev refuses to run in production.", file=sys.stderr)
        return 1
    password = os.environ.get("SITESENSE_DEMO_PASSWORD", "")
    try:
        validate_password(password)
    except PasswordPolicyError as exc:
        print(f"Set SITESENSE_DEMO_PASSWORD to a valid password first: {exc}", file=sys.stderr)
        return 1

    database = Database(settings)
    with database.session_factory() as db:
        sites: dict[str, Site] = {s.code: s for s in db.scalars(select(Site)).all()}
        for code, name, location, lat, lon in DEMO_SITES:
            if code not in sites:
                sites[code] = Site(code=code, name=name, location=location, latitude=lat, longitude=lon)
                db.add(sites[code])
        db.flush()

        password_hash = hash_password(password)
        created = 0
        for email, full_name, role, site_codes in DEMO_USERS:
            existing = db.scalar(select(User).where(User.email == email))
            if existing is not None:
                existing.is_demo = True  # in demo mode, skips two-step enforcement (Phase 13)
                continue
            db.add(
                User(
                    email=email,
                    full_name=full_name,
                    role=role.value,
                    password_hash=password_hash,
                    must_change_password=False,
                    is_demo=True,
                    sites=[sites[c] for c in site_codes],
                )
            )
            created += 1
        db.commit()

        qs = db.scalar(select(User).where(User.email == "qs@sitesense.example"))
        new_projects = 0
        for code, name, site_code, client, kind, status, value, start, end, boq_file in DEMO_PROJECTS:
            if db.scalar(select(Project).where(Project.code == code)):
                continue
            project = Project(
                code=code,
                name=name,
                site_id=sites[site_code].id,
                client_name=client,
                project_type=kind,
                status=status,
                contract_value=value,
                start_date=start,
                planned_end=end,
            )
            db.add(project)
            db.commit()
            new_projects += 1
            if boq_file and qs is not None:
                parsed = parse_boq(boq_file, (SEED_DATA / boq_file).read_bytes())
                import_boq(
                    db,
                    project,
                    parsed,
                    file_name=boq_file,
                    dry_run=False,
                    actor=qs,
                    meta=RequestMeta(ip_address=None, user_agent="seed-dev"),
                )
        for code, programme in DEMO_PROGRAMMES.items():
            target = db.scalar(select(Project).where(Project.code == code))
            if target is None or db.scalar(select(Task).where(Task.project_id == target.id)):
                continue
            _seed_programme(db, target, programme, DEMO_PACE[code])
        _seed_reports(db)
        _seed_materials(db)
        _seed_supplier_history(db)
        _seed_risk_inputs(db)
        _seed_issues(db)
        _seed_contract(db)
        risk_service.score_all(db)
        cost_service.check_all(db)
        _seed_portal(db, LocalStorage(settings.media_root))
    database.dispose()
    print(
        f"Seeded {len(DEMO_SITES)} sites, {created} new demo users and {new_projects} new projects "
        "(password: SITESENSE_DEMO_PASSWORD)."
    )
    return 0


def _seed_programme(
    db: Session,
    project: Project,
    programme: list[tuple[str, str, str | None, date, date, Decimal]],
    pace: float,
) -> None:
    """Tasks with progress as of today, plus weekly history, so the S-curve has a real actual line."""
    today = clock.site_today()
    sections = {
        s.code: s.id for s in db.scalars(select(BoqSection).where(BoqSection.project_id == project.id))
    }

    def done(plan: TaskPlan, on: date) -> Decimal:
        # Work runs at ``pace`` of the plan's speed: a slow task finishes late, but it does finish.
        days = (plan.planned_end - plan.planned_start).days
        stretched = TaskPlan(
            plan.planned_start, plan.planned_start + timedelta(days=round(days / pace)), plan.weight
        )
        value = min(planned_fraction(stretched, on) * 100, 100.0)
        return Decimal(str(round(value, 1)))

    def finished_on(plan: TaskPlan) -> date:
        day = plan.planned_start
        while done(plan, day) < 100:
            day += timedelta(days=1)
        return day

    plans = [TaskPlan(start, end, weight) for _, _, _, start, end, weight in programme]
    created: dict[str, Task] = {}
    for position, ((code, name, section, start, end, weight), plan) in enumerate(
        zip(programme, plans, strict=True)
    ):
        progress = done(plan, today)
        created[code] = Task(
            project_id=project.id,
            code=code,
            name=name,
            boq_section_id=sections.get(section or ""),
            planned_start=start,
            planned_end=end,
            weight=weight,
            percent_complete=progress,
            position=position + 1,
            is_concrete_pour=code in DEMO_POURS.get(project.code, set()),
            actual_start=start if progress > 0 else None,
            actual_finish=finished_on(plan) if progress >= 100 else None,
        )
        db.add(created[code])
    db.flush()
    pm = db.scalar(select(User).where(User.email == "pm@sitesense.example"))
    assert pm is not None  # the demo users are created before the programmes
    for before, after, lag in DEMO_LINKS.get(project.code, []):
        db.add(
            TaskDependency(
                project_id=project.id,
                predecessor_id=created[before].id,
                successor_id=created[after].id,
                lag_days=lag,
                created_by=pm.id,
                created_at=clock.utcnow(),
            )
        )
    for on in week_dates(project.start_date, today):
        history = [TaskPlan(p.planned_start, p.planned_end, p.weight, done(p, on)) for p in plans]
        db.add(
            ProgressSnapshot(
                project_id=project.id, snapshot_date=on, actual_percent=Decimal(str(actual_percent(history)))
            )
        )
    db.commit()


def _seed_reports(db: Session) -> None:
    """A week of Havelock reports by the demo engineer; today's is left for you to file."""
    project = db.scalar(select(Project).where(Project.code == "HR-2026-01"))
    engineer = db.scalar(select(User).where(User.email == "engineer@sitesense.example"))
    if project is None or engineer is None:
        return
    if db.scalar(select(DailyReport).where(DailyReport.project_id == project.id)):
        return
    today = clock.site_today()
    for days_ago, crew, summary, rain, work_done, problems in DEMO_REPORTS:
        db.add(
            DailyReport(
                project_id=project.id,
                author_id=engineer.id,
                report_date=today - timedelta(days=days_ago),
                weather_summary=summary,
                temp_max_c=Decimal("30.5"),
                temp_min_c=Decimal("24.0"),
                rain_mm=rain,
                weather_source="manual",
                crew_count=crew,
                work_done=work_done,
                problems=problems,
                submitted_at=clock.utcnow() - timedelta(days=days_ago, hours=-1),
            )
        )
    db.commit()


def _seed_materials(db: Session) -> None:
    """Suppliers and a set of Havelock material requests at every stage, made through the services
    so numbering, history, notifications and the rules are exactly what the app produces."""
    for name, contact, phone, categories in DEMO_SUPPLIERS:
        if not db.scalar(select(Supplier).where(Supplier.name == name)):
            db.add(Supplier(name=name, contact_name=contact, phone=phone, categories=categories))
    db.commit()

    project = db.scalar(select(Project).where(Project.code == "HR-2026-01"))
    people = {
        u.email.split("@")[0]: u
        for u in db.scalars(select(User).where(User.email.like("%@sitesense.example")))
    }
    if project is None or db.scalar(select(MaterialRequest).where(MaterialRequest.project_id == project.id)):
        return
    engineer, qs, pm, buyer = people["engineer"], people["qs"], people["pm"], people["procurement"]
    meta = RequestMeta(ip_address=None, user_agent="seed-dev")
    today = clock.site_today()
    for code, quantity, price, days, stage, supplier_name, delivered in DEMO_REQUESTS:
        item = db.scalar(select(BoqItem).where(BoqItem.project_id == project.id, BoqItem.item_code == code))
        if item is None:
            continue
        request = materials_service.create_request(
            db,
            engineer,
            RequestCreate(
                project_id=project.id,
                boq_item_id=item.id,
                quantity=Decimal(quantity),
                # Engineers do not see rates: the request starts at the budgeted rate and the QS
                # prices it at the QS check below.
                unit_price=None,
                needed_by=today + timedelta(days=days),
                notes=None,
            ),
            meta=meta,
        )
        if stage == "requested":
            continue
        if stage == "change_requested":
            materials_service.decide(
                db,
                qs,
                request.id,
                DecisionIn(decision="request_change", comment="Split it by floor, please."),
                meta=meta,
            )
            continue
        materials_service.decide(
            db, qs, request.id, DecisionIn(decision="approve", unit_price=Decimal(price)), meta=meta
        )
        if stage == "pm_approval":
            continue
        if request.status == "pm_approval":
            materials_service.decide(db, pm, request.id, DecisionIn(decision="approve"), meta=meta)
        if stage == "approved" or supplier_name is None:
            continue
        supplier = db.scalar(select(Supplier).where(Supplier.name == supplier_name))
        assert supplier is not None
        outcome = procurement_service.create_order(
            db,
            buyer,
            PurchaseOrderCreate(
                supplier_id=supplier.id,
                expected_delivery=today + timedelta(days=days),
                lines=[OrderLineIn(request_id=request.id)],
            ),
            meta=meta,
        )
        po = outcome.order
        if delivered and po is not None:
            procurement_service.record_delivery(
                db,
                buyer,
                po.id,
                DeliveryIn(request_id=request.id, quantity=Decimal(delivered), delivered_on=today),
                meta=meta,
            )


def _seed_supplier_history(db: Session) -> None:
    """A finished job with a year of deliveries, so each demo supplier has an on-time record (BR-12).

    Completed projects are never risk-scored, so this history does not change the demo projects' risk.
    Each supplier's late orders are spread through its record; dates are relative to today.
    """
    code, name, client = DEMO_HISTORY_PROJECT
    if db.scalar(select(Project).where(Project.code == code)):
        return
    site = db.scalar(select(Site).where(Site.code == "NEG-04"))
    engineer = db.scalar(select(User).where(User.email == "engineer@sitesense.example"))
    buyer = db.scalar(select(User).where(User.email == "procurement@sitesense.example"))
    assert site is not None
    assert engineer is not None
    assert buyer is not None
    today = clock.site_today()
    project = Project(
        code=code, name=name, site_id=site.id, client_name=client, project_type="industrial",
        status="completed", contract_value=Decimal("240000000.00"), start_date=today - timedelta(days=420),
        planned_end=today - timedelta(days=40),
    )  # fmt: skip
    db.add(project)
    db.flush()
    section = BoqSection(project_id=project.id, code="B", name="Structure and envelope", position=1)
    db.add(section)
    db.flush()
    for position, (supplier_name, item_facts, orders, on_time) in enumerate(DEMO_SUPPLIER_HISTORY, start=1):
        item_code, description, unit, rate = item_facts
        supplier = db.scalar(select(Supplier).where(Supplier.name == supplier_name))
        assert supplier is not None
        item = BoqItem(
            project_id=project.id, section_id=section.id, item_code=item_code, description=description,
            unit=unit, quantity=Decimal("1000"), rate=Decimal(rate), amount=Decimal(rate) * 1000,
            position=position,
        )  # fmt: skip
        db.add(item)
        db.flush()
        late_count = orders - on_time
        late = {round((k + 0.5) * orders / late_count) for k in range(late_count)} if late_count else set()
        for i in range(orders):
            expected = today - timedelta(days=380 - i * (330 // orders))
            shift = 3 + i % 8 if i in late else -(i % 2)  # late by days, or on the day or the day before
            arrived = expected + timedelta(days=shift)
            submitted = datetime.combine(expected - timedelta(days=21), time(9), clock.SITE_TIME_ZONE)
            request = MaterialRequest(
                number=materials_service.next_number(db, "MR"), project_id=project.id,
                boq_item_id=item.id, requested_by=engineer.id, quantity=Decimal("10"),
                unit_price=Decimal(rate), needed_by=expected, status="delivered", approval_level="qs",
                submitted_at=submitted,
            )  # fmt: skip
            order = PurchaseOrder(
                number=materials_service.next_number(db, "PO"), project_id=project.id,
                supplier_id=supplier.id, issued_by=buyer.id, issued_at=submitted + timedelta(days=7),
                expected_delivery=expected, status="delivered",
            )  # fmt: skip
            db.add_all([request, order])
            db.flush()
            line = PurchaseOrderLine(
                purchase_order_id=order.id, request_id=request.id, quantity=Decimal("10"),
                unit_price=Decimal(rate), amount=Decimal(rate) * 10, position=1,
            )  # fmt: skip
            db.add(line)
            db.flush()
            received = datetime.combine(arrived, time(15), clock.SITE_TIME_ZONE)
            db.add(
                Delivery(
                    line_id=line.id, quantity=Decimal("10"), delivered_on=arrived, received_by=buyer.id,
                    created_at=received,
                )
            )  # fmt: skip
    db.commit()


def _seed_risk_inputs(db: Session) -> None:
    """What the risk model reads, so every demo project gets a meaningful score: planned crews, a few
    weeks of reports (Havelock short-handed with gaps, Peradeniya fully staffed) and two late
    Havelock deliveries. Safe to run again: each part checks whether it is already there."""
    today = clock.site_today()
    projects = {p.code: p for p in db.scalars(select(Project).where(Project.code.in_(DEMO_CREWS)))}
    for code, crew in DEMO_CREWS.items():
        if code in projects and projects[code].planned_crew is None:
            projects[code].planned_crew = crew
    engineer = db.scalar(select(User).where(User.email == "engineer@sitesense.example"))
    pm = db.scalar(select(User).where(User.email == "pm@sitesense.example"))

    def file(project: Project, author: User, days_ago: int, crew: int) -> None:
        day = today - timedelta(days=days_ago)
        if day.weekday() == 6 or day < project.start_date:
            return
        if db.scalar(
            select(DailyReport).where(DailyReport.project_id == project.id, DailyReport.report_date == day)
        ):
            return
        db.add(
            DailyReport(
                project_id=project.id, author_id=author.id, report_date=day, weather_summary="Partly cloudy",
                rain_mm=Decimal("0.0"), weather_source="manual", crew_count=crew,
                work_done=WORKS[days_ago % len(WORKS)],
                submitted_at=clock.utcnow() - timedelta(days=days_ago),
            )
        )  # fmt: skip

    havelock, peradeniya = projects.get("HR-2026-01"), projects.get("PRO-2026-02")
    if havelock is not None and engineer is not None:
        for days_ago, crew in HR_EARLIER_REPORTS.items():
            file(havelock, engineer, days_ago, crew)
        # Two orders turned up late (seed only: orders are normally placed with a future date).
        for line in db.scalars(
            select(PurchaseOrderLine).join(PurchaseOrder).where(PurchaseOrder.project_id == havelock.id)
        ):
            po = line.purchase_order
            if po.expected_delivery < today:
                continue
            po.expected_delivery = today - timedelta(days=4 if line.deliveries else 9)
            for delivery in line.deliveries:
                delivery.delivered_on = today - timedelta(days=1)
    if peradeniya is not None and pm is not None:
        for days_ago in range(14):
            file(peradeniya, pm, days_ago, 41 + days_ago % 4)
    db.commit()


def _seed_issues(db: Session) -> None:
    """Tag the demo reports' problems with the shipped classifier and record the confident tags as
    confirmed by their authors, so the demo has issues and the risk model sees them. Low-confidence
    tags are left out, as a careful engineer would remove or correct them. Reports that already have
    issues are left alone."""
    for report in db.scalars(select(DailyReport).where(DailyReport.problems.is_not(None))):
        if db.scalar(select(ReportIssue).where(ReportIssue.report_id == report.id)):
            continue
        now = clock.utcnow()
        tags = [t for t in tag_problems(report.problems, [report.author.full_name]) if not t.low_confidence]
        for position, tag in enumerate(tags):
            db.add(
                ReportIssue(
                    report_id=report.id, project_id=report.project_id, snippet=tag.snippet,
                    category=tag.category, severity=tag.severity, status="confirmed", source="ai",
                    ai_category=tag.category, ai_severity=tag.severity,
                    confidence=Decimal(str(tag.confidence)), low_confidence=False,
                    model_version=tag.model_version,
                    position=position, created_at=now, confirmed_by=report.author_id, confirmed_at=now,
                )
            )  # fmt: skip
    db.commit()


def _seed_contract(db: Session) -> None:
    """Havelock's claims and variations at every stage, through the services (BR-08, BR-09).

    Claims: one approved and paid, one waiting for the PM. Certified progress follows the programme's
    progress in each BOQ section. Variations: one the PM approved (small, raised by the QS), one with
    a time impact waiting for the client, and one the PM raised that the QS has still to price.
    """
    project = db.scalar(select(Project).where(Project.code == "HR-2026-01"))
    if project is None or db.scalar(select(ProgressClaim.id).where(ProgressClaim.project_id == project.id)):
        return
    people = {
        u.email.split("@")[0]: u
        for u in db.scalars(select(User).where(User.email.like("%@sitesense.example")))
    }
    qs, pm = people["qs"], people["pm"]
    meta = RequestMeta(ip_address=None, user_agent="seed-dev")
    sections = list(
        db.scalars(
            select(BoqSection).where(BoqSection.project_id == project.id).order_by(BoqSection.position)
        )
    )
    progress: dict[object, Decimal] = {}
    for section in sections:
        tasks = list(db.scalars(select(Task).where(Task.boq_section_id == section.id)))
        weight = sum((t.weight for t in tasks), Decimal(0))
        done = sum((t.weight * t.percent_complete for t in tasks), Decimal(0))
        progress[section.id] = (done / weight).quantize(Decimal("1")) if weight else Decimal(0)

    def claim(share: Decimal) -> ClaimIn:
        return ClaimIn(
            sections=[
                ClaimSectionIn(
                    section_id=s.id, certified_pct=(progress[s.id] * share).quantize(Decimal("0.5"))
                )
                for s in sections
            ]
        )

    if any(progress.values()):
        first = claim_service.create(db, qs, project.id, claim(Decimal("0.7")), meta=meta)
        claim_service.decide(db, pm, first.id, ClaimDecisionIn(decision="approve"), meta=meta)
        claim_service.record_payment(db, qs, first.id, ClaimPaymentIn(paid_on=clock.site_today()), meta=meta)
        claim_service.create(db, qs, project.id, claim(Decimal("1")), meta=meta)

    by_code = {s.code: s for s in sections}
    first_section, last_section = sections[0], by_code.get("C", sections[-1])
    slab = db.scalar(
        select(Task).where(Task.project_id == project.id, Task.boq_section_id == last_section.id)
    )
    small = variation_service.raise_variation(
        db, qs, project.id,
        VariationIn(
            title="Extra waterproofing to the basement retaining wall",
            description="Ground water is higher than surveyed; a second membrane layer is needed.",
            section_id=first_section.id, contract_change=Decimal("850000"), budget_change=Decimal("680000"),
        ),
        meta=meta,
    )  # fmt: skip
    variation_service.decide(db, pm, small.id, VariationDecisionIn(decision="approve"), meta=meta)
    if slab is not None:
        variation_service.raise_variation(
            db, qs, project.id,
            VariationIn(
                title="Additional plant room on the roof",
                description="The client asked for a roof-top plant room for future solar inverters.",
                section_id=last_section.id, task_id=slab.id, time_impact_days=10,
                contract_change=Decimal("4200000"), budget_change=Decimal("3300000"),
            ),
            meta=meta,
        )  # fmt: skip
    variation_service.raise_variation(
        db, pm, project.id,
        VariationIn(
            title="Granite floor in the main lobby",
            description="Upgrade the lobby floor finish from homogeneous tiles to polished granite.",
            section_id=last_section.id,
        ),
        meta=meta,
    )  # fmt: skip


DEMO_MILESTONES = {
    "T-020": "Foundations complete",
    "T-050": "Structure complete",
    "T-070": "Roof complete",
    "T-090": "Finishes complete",
    "T-110": "Handover",
}
# (days ago, levels of frame drawn, caption)
DEMO_PHOTOS = [
    (5, 3, "Level 3 slab poured, north side"),
    (4, 4, "Level 4 columns and formwork"),
    (2, 4, "Level 4 slab reinforcement before the pour"),
    (1, 5, "Level 5 starter bars"),
]


def _demo_photo(levels: int) -> bytes:
    """A drawn picture of the frame going up (the demo has no real site photos)."""
    from PIL import Image, ImageDraw

    width, height = 1200, 800
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):  # sky
        shade = int(200 + 40 * y / height)
        draw.line([(0, y), (width, y)], fill=(150, shade - 20, 235))
    draw.rectangle([0, 640, width, height], fill=(121, 104, 82))  # ground
    floor = 80
    left, right = 300, 900
    for level in range(levels + 1):
        y = 640 - level * floor
        draw.rectangle([left - 20, y - 14, right + 20, y], fill=(176, 176, 170))  # slab
        if level < levels:
            for x in range(left, right + 1, 120):
                draw.rectangle([x - 10, y - floor, x + 10, y - 14], fill=(160, 160, 154))  # columns
    top = 640 - levels * floor
    for x in range(left + 60, right, 120):  # starter bars
        draw.line([(x, top - 14), (x, top - 60)], fill=(120, 60, 40), width=3)
    draw.line([(1020, 640), (1020, 120)], fill=(240, 190, 30), width=14)  # crane mast
    draw.line([(700, 130), (1150, 130)], fill=(240, 190, 30), width=10)  # jib
    draw.line([(820, 130), (820, top - 40)], fill=(60, 60, 60), width=2)  # hook line
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88)
    return out.getvalue()


def _seed_portal(db: Session, storage: LocalStorage) -> None:
    """The client portal for Havelock: milestones, a published handover date, and shared photos."""
    project = db.scalar(select(Project).where(Project.code == "HR-2026-01"))
    pm = db.scalar(select(User).where(User.email == "pm@sitesense.example"))
    engineer = db.scalar(select(User).where(User.email == "engineer@sitesense.example"))
    if project is None or pm is None or engineer is None:
        return
    client = db.scalar(select(User).where(User.email == "client@sitesense.example"))
    if client is not None and project not in client.client_projects:
        client.client_projects = [*client.client_projects, project]  # the client sees Havelock only
    db.commit()
    if db.scalar(select(HandoverPublication.id).where(HandoverPublication.project_id == project.id)):
        return
    meta = RequestMeta(ip_address=None, user_agent="seed-dev")

    for task in db.scalars(select(Task).where(Task.project_id == project.id)):
        if task.code in DEMO_MILESTONES:
            task.client_milestone = True
            task.milestone_name = DEMO_MILESTONES[task.code]
    db.commit()

    # An earlier date published at the start, then today's, which follows the programme.
    first = handover_service.publish(
        db, pm, project,
        HandoverIn(handover_date=project.planned_end, reason="The contract date: work is starting on plan."),
        meta=meta,
    )  # fmt: skip
    first.published_at = clock.utcnow() - timedelta(days=150)
    db.commit()
    forecast = handover_service.programme_forecast(db, project) or project.planned_end
    handover_service.publish(
        db, pm, project,
        HandoverIn(
            handover_date=max(forecast, project.planned_end),
            reason="Heavy October rain held up the frame; the forecast includes the catch-up plan.",
        ),
        meta=meta,
    )  # fmt: skip

    reports = {
        (clock.site_today() - r.report_date).days: r
        for r in db.scalars(select(DailyReport).where(DailyReport.project_id == project.id))
    }
    shared: list[uuid.UUID] = []
    for days_ago, levels, caption in DEMO_PHOTOS:
        report = reports.get(days_ago)
        if report is None:
            continue
        # Through the same processing as an upload, onto an earlier report (uploads close after the day).
        processed = photos.process(_demo_photo(levels))
        stem = uuid.uuid4().hex
        storage.save(f"{stem}.jpg", processed.full)
        storage.save(f"{stem}_thumb.jpg", processed.thumb)
        photo = ReportPhoto(
            report_id=report.id, uploaded_by=engineer.id, storage_key=f"{stem}.jpg",
            content_type="image/jpeg",
            size_bytes=len(processed.full), width=processed.width, height=processed.height, caption=caption,
            position=1, created_at=report.submitted_at,
        )  # fmt: skip
        db.add(photo)
        db.flush()
        if days_ago != 1:  # the newest stays private: the PM has not looked at it yet
            shared.append(photo.id)
    if shared:
        portal_service.set_shared(db, pm, project, PhotosShareIn(photo_ids=shared, shared=True), meta=meta)


def send_reminders() -> int:
    database = Database(get_settings())
    created = run_report_reminders(database.session_factory)
    database.dispose()
    print(f"Created {created} reminder notifications.")
    return 0


def refresh_site_weather() -> int:
    settings = get_settings()
    database = Database(settings)
    refreshed = refresh_weather(database.session_factory, OpenMeteoClient(settings.weather_timeout_seconds))
    database.dispose()
    print(f"Refreshed the forecast for {refreshed} sites.")
    return 0


def score_risk() -> int:
    database = Database(get_settings())
    scored = run_risk_scoring(database.session_factory)
    database.dispose()
    print(f"Scored {scored} projects.")
    return 0


def check_variance() -> int:
    database = Database(get_settings())
    alerts = run_variance_check(database.session_factory)
    database.dispose()
    print(f"Checked cost forecasts: {alerts} new overrun alerts.")
    return 0


def check_pours() -> int:
    database = Database(get_settings())
    sent = run_pour_check(database.session_factory)
    database.dispose()
    print(f"Checked concrete pours against the forecast: {sent} alerts.")
    return 0


def strip_photo_metadata(dry_run: bool) -> int:
    """One-off (Phase 12): re-encode stored photos that still carry a comment or other metadata."""
    settings = get_settings()
    database = Database(settings)
    with database.session_factory() as db:
        result = report_service.strip_stored_metadata(db, LocalStorage(settings.media_root), dry_run=dry_run)
    database.dispose()
    verb = "would clean" if dry_run else "cleaned"
    print(f"Checked {result.photos} photos: {verb} {result.cleaned} files; {result.missing} files missing.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create a Company Admin with a temporary password")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    sub.add_parser("seed-dev", help="create demo sites and one user per role (not in production)")
    sub.add_parser("send-reminders", help="remind sites missing today's daily report")
    sub.add_parser("refresh-weather", help="fetch the 14-day forecast for every active site")
    sub.add_parser("score-risk", help="score every open project's risk now")
    sub.add_parser("check-variance", help="forecast final cost per section and alert new overruns")
    sub.add_parser("check-pours", help="BR-06: alert PMs about concrete pours on heavy-rain days")
    strip = sub.add_parser(
        "strip-photo-metadata", help="re-encode stored photos that still carry a comment or other metadata"
    )
    strip.add_argument("--dry-run", action="store_true", help="count the files, change nothing")
    args = parser.parse_args(argv)

    if args.command == "create-admin":
        return create_admin(args.email, args.name)
    if args.command == "send-reminders":
        return send_reminders()
    if args.command == "refresh-weather":
        return refresh_site_weather()
    if args.command == "score-risk":
        return score_risk()
    if args.command == "check-variance":
        return check_variance()
    if args.command == "check-pours":
        return check_pours()
    if args.command == "strip-photo-metadata":
        return strip_photo_metadata(args.dry_run)
    return seed_dev()


if __name__ == "__main__":
    raise SystemExit(main())
