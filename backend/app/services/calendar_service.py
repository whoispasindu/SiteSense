"""Holidays and each project's working calendar (Phase 9).

Holidays are company-wide (public holidays and other days off, such as Poya days in Sri Lanka) and
only the Company Admin changes them (``holidays:manage``); every change is audited. The admin can
import a country's public holidays for a year (the ``holidays`` package, offline data) and then edit
them. A project's calendar is its working week plus those
holidays. When next year has no holidays yet, the admin's holiday page warns, and a programme that
runs into a year without any shows a warning on the Gantt view.
"""

from __future__ import annotations

import uuid
from datetime import date

import holidays
from sqlalchemy import extract, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models import Holiday, Project, User
from app.rules.calendar import WorkCalendar, parse_week
from app.schemas.schedule import (
    HolidayCountries,
    HolidayImportIn,
    HolidayImportOut,
    HolidayIn,
    HolidayList,
    HolidayOut,
)
from app.services import audit
from app.services.audit import AuditAction, RequestMeta


def holiday_dates(db: Session) -> frozenset[date]:
    return frozenset(db.scalars(select(Holiday.holiday_date)).all())


def calendar_for(db: Session, project: Project, holidays: frozenset[date] | None = None) -> WorkCalendar:
    return WorkCalendar(
        weekdays=parse_week(project.working_week),
        holidays=holiday_dates(db) if holidays is None else holidays,
    )


def years_with_holidays(db: Session) -> set[int]:
    return {int(y) for y in db.scalars(select(extract("year", Holiday.holiday_date)).distinct()).all()}


def missing_years(db: Session, first: date, last: date) -> list[int]:
    """Years from ``first`` to ``last`` that have no holidays entered."""
    have = years_with_holidays(db)
    return [y for y in range(first.year, last.year + 1) if y not in have]


def list_holidays(db: Session) -> HolidayList:
    rows = db.scalars(select(Holiday).order_by(Holiday.holiday_date)).all()
    years = sorted({h.holiday_date.year for h in rows})
    return HolidayList(
        holidays=[HolidayOut(id=h.id, holiday_date=h.holiday_date, name=h.name) for h in rows],
        years=years,
        missing_next_year=clock.site_today().year + 1 not in years,
    )


def add_holiday(db: Session, admin: User, data: HolidayIn, *, meta: RequestMeta) -> HolidayOut:
    holiday = Holiday(
        holiday_date=data.holiday_date, name=data.name, created_by=admin.id, created_at=clock.utcnow()
    )
    db.add(holiday)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("That date is already a holiday.") from exc
    audit.record(
        db,
        AuditAction.HOLIDAY_ADDED,
        meta=meta,
        actor_id=admin.id,
        target_type="holiday",
        target_id=holiday.id,
        details={"date": data.holiday_date.isoformat(), "name": data.name},
    )
    db.commit()
    return HolidayOut(id=holiday.id, holiday_date=holiday.holiday_date, name=holiday.name)


def remove_holiday(db: Session, admin: User, holiday_id: uuid.UUID, *, meta: RequestMeta) -> None:
    holiday = db.get(Holiday, holiday_id)
    if holiday is None:
        raise NotFoundError("Holiday not found.")
    details = {"date": holiday.holiday_date.isoformat(), "name": holiday.name}
    db.delete(holiday)
    audit.record(
        db,
        AuditAction.HOLIDAY_REMOVED,
        meta=meta,
        actor_id=admin.id,
        target_type="holiday",
        target_id=holiday_id,
        details=details,
    )
    db.commit()


def holiday_countries(default: str) -> HolidayCountries:
    return HolidayCountries(countries=sorted(holidays.list_supported_countries()), default=default)


def _public_holidays(country: str, year: int) -> dict[date, str]:
    try:
        calendar = holidays.country_holidays(country, years=year)
    except NotImplementedError as exc:
        raise BusinessRuleError(f"SiteSense has no public holiday list for {country}.") from exc
    # English names where the country's list has them (Sri Lanka's default is Sinhala).
    english = next(
        (lang for lang in ("en_US", "en_GB") if lang in (calendar.supported_languages or ())), None
    )
    if english is not None:
        calendar = holidays.country_holidays(country, years=year, language=english)
    return {day: name[:80] for day, name in calendar.items()}


def import_holidays(
    db: Session, admin: User, data: HolidayImportIn, *, meta: RequestMeta
) -> HolidayImportOut:
    found = _public_holidays(data.country, data.year)
    existing = holiday_dates(db)
    added: list[Holiday] = []
    for day, name in sorted(found.items()):
        if day in existing:
            continue
        holiday = Holiday(holiday_date=day, name=name, created_by=admin.id, created_at=clock.utcnow())
        db.add(holiday)
        added.append(holiday)
    already = len(found) - len(added)
    if not found:
        message = (
            f"No public holidays are published for {data.country} in {data.year} yet. "
            "Add them one by one when they are announced."
        )
    elif not added:
        message = f"All {len(found)} public holidays for {data.year} were already entered."
    else:
        message = f"Added {len(added)} public holidays for {data.year}."
        if already:
            message += f" {already} were already entered."
        message += " Check them, and add any other days your sites do not work."
    if added:
        db.flush()
        audit.record(
            db,
            AuditAction.HOLIDAYS_IMPORTED,
            meta=meta,
            actor_id=admin.id,
            target_type="holiday",
            target_id=None,
            details={"country": data.country, "year": data.year, "added": len(added)},
        )
        db.commit()
    return HolidayImportOut(
        country=data.country,
        year=data.year,
        added=[HolidayOut(id=h.id, holiday_date=h.holiday_date, name=h.name) for h in added],
        already_entered=already,
        message=message,
    )
