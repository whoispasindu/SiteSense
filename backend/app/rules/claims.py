"""Progress claims: the BR-08 calculation and its checks (Phase 8).

BR-08: a claim cannot exceed certified progress times contract value, minus previous claims and
5% retention. The QS certifies a percentage complete for each BOQ section; the claim is then
calculated, never typed in, so it cannot exceed the limit:

    certified %       = the sections' percentages weighted by their contract value
    certified value   = certified % x contract value          (gross, to date)
    retention         = 5% of the certified value             (held back, to date)
    this claim        = certified value - retention - previous claims

"Previous claims" are the amounts of earlier claims the PM approved (paid or not). A section's
contract value is its BOQ amount plus the approved variations in it, so the weights follow the
contract as it changes.

Pure functions over plain values; tested in ``tests/test_rules_claims.py``.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.rules.materials import ZERO, RuleResult, money

RETENTION = Decimal("0.05")  # BR-08
HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class SectionProgress:
    section_id: uuid.UUID
    value: Decimal  # the section's contract value: BOQ amount plus approved variations
    certified_pct: Decimal  # this claim, 0 to 100, cumulative
    previous_pct: Decimal  # the last approved claim's figure for this section (0 if none)


@dataclass(frozen=True, slots=True)
class ClaimFigures:
    certified_pct: Decimal  # overall, value-weighted, not rounded
    certified_value: Decimal
    retention: Decimal
    previous_claims: Decimal
    amount: Decimal  # this claim

    @property
    def limit(self) -> Decimal:
        """BR-08's ceiling for this claim (the amount equals it by construction)."""
        return money(self.certified_value * (1 - RETENTION)) - self.previous_claims


def calculate(
    *, contract_value: Decimal, sections: list[SectionProgress], previous_claims: Decimal
) -> ClaimFigures:
    total = sum((s.value for s in sections), ZERO)
    weighted = sum((s.value * s.certified_pct for s in sections), ZERO)
    certified_pct = weighted / total if total > ZERO else ZERO
    certified_value = money(contract_value * certified_pct / HUNDRED)
    retention = money(certified_value * RETENTION)
    return ClaimFigures(
        certified_pct=certified_pct,
        certified_value=certified_value,
        retention=retention,
        previous_claims=previous_claims,
        amount=certified_value - retention - previous_claims,
    )


def check(sections: list[SectionProgress], figures: ClaimFigures) -> list[RuleResult]:
    """Problems that stop the claim being submitted (empty: it may be submitted)."""
    problems = []
    for s in sections:
        if not ZERO <= s.certified_pct <= HUNDRED:
            problems.append(
                RuleResult("BR-08", "block", "Certified progress must be between 0% and 100%.",
                           {"section_id": str(s.section_id)})
            )  # fmt: skip
        elif s.certified_pct < s.previous_pct:
            problems.append(
                RuleResult(
                    "BR-08",
                    "block",
                    f"Certified progress cannot go below the last approved claim ({s.previous_pct}%).",
                    {"section_id": str(s.section_id), "previous_pct": str(s.previous_pct)},
                )
            )
    if not problems and figures.amount <= ZERO:
        problems.append(
            RuleResult(
                "BR-08",
                "block",
                "Nothing to claim: certified progress less retention does not exceed the previous claims.",
                {"amount": str(figures.amount), "previous_claims": str(figures.previous_claims)},
            )
        )
    return problems
