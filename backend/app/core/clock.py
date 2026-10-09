"""Single source of "now" so time-dependent rules (lockouts, token expiry) are testable."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
