"""Single source of "now" so time-dependent rules (lockouts, token expiry) are testable."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.core import company


def site_zone() -> ZoneInfo:
    """The company's time zone (``SITESENSE_TIME_ZONE``): "today" on site is the date there."""
    return company.current().time_zone


def utcnow() -> datetime:
    return datetime.now(UTC)


def site_today() -> date:
    return utcnow().astimezone(site_zone()).date()
