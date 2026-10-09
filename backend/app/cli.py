"""Operator commands.

    python -m app.cli create-admin --email admin@company.lk --name "Nimal Perera"
    python -m app.cli seed-dev            # local development only

``create-admin`` prints a one-time temporary password; the admin must change it at first sign-in.
``seed-dev`` creates demo sites and one account per role using SITESENSE_DEMO_PASSWORD, and
refuses to run in production.
"""

import argparse
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.database import Database
from app.core.permissions import Role
from app.core.security import (
    PasswordPolicyError,
    generate_temporary_password,
    hash_password,
    validate_password,
)
from app.models import BoqSection, ProgressSnapshot, Project, Site, Task, User
from app.services import audit
from app.services.audit import RequestMeta
from app.services.auth_service import normalize_email
from app.services.boq_import import parse_boq
from app.services.progress import TaskPlan, actual_percent, planned_fraction, week_dates
from app.services.project_service import import_boq

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create a Company Admin with a temporary password")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    sub.add_parser("seed-dev", help="create demo sites and one user per role (not in production)")
    args = parser.parse_args(argv)

    if args.command == "create-admin":
        return create_admin(args.email, args.name)
    return seed_dev()


if __name__ == "__main__":
    raise SystemExit(main())
