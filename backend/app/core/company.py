"""The company's country, time zone and currency, for code that has no settings object at hand.

Set once per process from the settings (``configure``): by ``create_app``, the CLI and the scheduler
process. Until then, and in tests that do not configure it, the defaults are Sri Lanka's, as before
these became settings. Amounts are stored as plain decimals with no currency; only labels and
formatting use the currency code.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from app.core.config import Settings

# Currencies whose amounts have no minor unit (ISO 4217). Everything else is shown with 2 decimals;
# amounts are stored to 2 decimals, so a third (KWD, BHD, OMR and others) is not kept.
ZERO_DECIMAL_CURRENCIES = frozenset((
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "UYI", "VND", "VUV", "XAF",
    "XOF", "XPF",
))  # fmt: skip


@dataclass(frozen=True, slots=True)
class Company:
    time_zone: ZoneInfo
    country: str
    currency: str
    number_locale: str
    # LKR per unit of the currency: converts the contract value for the risk model only.
    lkr_per_unit: Decimal

    @property
    def currency_decimals(self) -> int:
        return 0 if self.currency in ZERO_DECIMAL_CURRENCIES else 2


DEFAULT = Company(ZoneInfo("Asia/Colombo"), "LK", "LKR", "en-LK", Decimal(1))

_current = DEFAULT


def configure(settings: Settings) -> Company:
    global _current
    _current = Company(
        time_zone=ZoneInfo(settings.time_zone),
        country=settings.country,
        currency=settings.currency,
        number_locale=settings.number_locale,
        lkr_per_unit=settings.lkr_per_unit,
    )
    return _current


def current() -> Company:
    return _current


def money(value: Decimal | float | int) -> str:
    """'LKR 1,250,000.00' (or 'JPY 1,250,000'): amounts in emails, alerts and messages."""
    c = _current
    return f"{c.currency} {value:,.{c.currency_decimals}f}"
