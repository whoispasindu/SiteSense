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

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import Database
from app.core.permissions import Role
from app.core.security import (
    PasswordPolicyError,
    generate_temporary_password,
    hash_password,
    validate_password,
)
from app.models import Site, User
from app.services import audit
from app.services.auth_service import normalize_email

DEMO_SITES = [
    ("COL-07", "Havelock Residences", "Colombo 05", 6.8836, 79.8650),
    ("KDY-02", "Peradeniya Road Offices", "Kandy", 7.2735, 80.6127),
    ("GAL-11", "Fort View Apartments", "Galle", 6.0329, 80.2168),
]

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
    database.dispose()
    print(f"Seeded {len(DEMO_SITES)} sites and {created} new demo users (password: SITESENSE_DEMO_PASSWORD).")
    return 0


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
