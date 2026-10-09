"""Single source of "now" so time-dependent rules (lockouts, token expiry) are testable."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

# SiteSense serves Sri Lankan contractors: "today" on site is the date in Colombo.
SITE_TIME_ZONE = ZoneInfo("Asia/Colombo")


def utcnow() -> datetime:
    return datetime.now(UTC)


def site_today() -> date:
    return utcnow().astimezone(SITE_TIME_ZONE).date()
