"""Operator commands.

    python -m app.cli create-admin --email admin@company.lk --name "Nimal Perera"
    python -m app.cli seed-dev            # local development only
    python -m app.cli send-reminders      # missing daily report reminders now (BR-07)
    python -m app.cli refresh-weather     # fetch the 14-day forecast for every active site
    python -m app.cli score-risk          # score every open project's risk now

``create-admin`` prints a one-time temporary password; the admin must change it at first sign-in.
``seed-dev`` creates demo sites and one account per role using SITESENSE_DEMO_PASSWORD, and
refuses to run in production.
"""

import argparse
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.database import Database
from app.core.permissions import Role
from app.core.scheduler import refresh_weather, run_report_reminders, run_risk_scoring
from app.core.security import (
    PasswordPolicyError,
    generate_temporary_password,
    hash_password,
    validate_password,
)
from app.integrations.weather import OpenMeteoClient
from app.models import (
    BoqItem,
    BoqSection,
    DailyReport,
    MaterialRequest,
    ProgressSnapshot,
    Project,
    PurchaseOrder,
    PurchaseOrderLine,
    Site,
    Supplier,
    Task,
    User,
)
from app.schemas.materials import DecisionIn, DeliveryIn, OrderLineIn, PurchaseOrderCreate, RequestCreate
from app.services import audit, materials_service, procurement_service, risk_service
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
            if db.scalar(select(User).where(User.email == email)):
                continue
            db.add(
                User(
                    email=email,
                    full_name=full_name,
                    role=role.value,
                    password_hash=password_hash,
                    must_change_password=False,
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
        _seed_risk_inputs(db)
        risk_service.score_all(db)
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
        value = min(planned_fraction(plan, on) * 100 * pace, 100.0)
        return Decimal(str(round(value, 1)))

    plans = [TaskPlan(start, end, weight) for _, _, _, start, end, weight in programme]
    for position, ((code, name, section, start, end, weight), plan) in enumerate(
        zip(programme, plans, strict=True)
    ):
        db.add(
            Task(
                project_id=project.id,
                code=code,
                name=name,
                boq_section_id=sections.get(section or ""),
                planned_start=start,
                planned_end=end,
                weight=weight,
                percent_complete=done(plan, today),
                position=position + 1,
                is_critical=code in {"T-020", "T-040", "T-050", "T-090", "T-030"},
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
    args = parser.parse_args(argv)

    if args.command == "create-admin":
        return create_admin(args.email, args.name)
    if args.command == "send-reminders":
        return send_reminders()
    if args.command == "refresh-weather":
        return refresh_site_weather()
    if args.command == "score-risk":
        return score_risk()
    return seed_dev()


if __name__ == "__main__":
    raise SystemExit(main())
