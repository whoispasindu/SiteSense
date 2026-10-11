"""Forecast final cost per BOQ section, and when a forecast overrun alerts (Phase 8).

Pure functions over plain values. The method is the one the build guide names: committed cost plus
the remaining work at the current cost trend.

- *Committed* is what the section has committed so far (approved requests at their price, orders at
  their order value, finished deliveries at what was delivered), as on the budget page since Phase 5.
- The *budgeted value of the committed work* is the same quantities at their budgeted rates.
- The *cost trend* is committed / budgeted value: 1.08 means the work bought so far cost 8% more
  than budgeted. With nothing committed yet there is no trend, and the forecast is the budget.
- The *remaining work* is the budget not yet covered by committed quantities.

    forecast final = committed + remaining budget x trend

So the trend found so far is assumed to continue. Early in a section it rests on little evidence,
which is why the result reports how much of the budget the trend is based on.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.rules.materials import ZERO, money

# A section whose forecast exceeds its budget by more than this alerts the PM and QS (on entry).
VARIANCE_ALERT = Decimal("0.05")


@dataclass(frozen=True, slots=True)
class Forecast:
    budget: Decimal
    final_cost: Decimal
    trend: Decimal | None  # committed / budgeted value of the committed work; None: nothing committed yet
    basis_share: Decimal  # share of the budget the trend is based on (0 to 1)

    @property
    def variance(self) -> Decimal:
        """Budget minus forecast: negative is a forecast overrun."""
        return self.budget - self.final_cost

    @property
    def variance_share(self) -> Decimal | None:
        """The variance as a share of the budget (None for a zero budget)."""
        return self.variance / self.budget if self.budget > ZERO else None

    @property
    def over_alert_line(self) -> bool:
        """True when the forecast exceeds the budget by more than VARIANCE_ALERT."""
        if self.budget <= ZERO:
            return self.final_cost > ZERO
        return self.final_cost > self.budget * (1 + VARIANCE_ALERT)


def forecast_final_cost(*, budget: Decimal, committed: Decimal, committed_budget_value: Decimal) -> Forecast:
    if committed_budget_value <= ZERO:
        # No trend yet: the forecast is the budget, plus anything committed at no budgeted value.
        return Forecast(budget=budget, final_cost=money(committed + budget), trend=None, basis_share=ZERO)
    trend = committed / committed_budget_value
    remaining = max(budget - committed_budget_value, ZERO)
    share = min(committed_budget_value / budget, Decimal(1)) if budget > ZERO else Decimal(1)
    return Forecast(
        budget=budget, final_cost=money(committed + remaining * trend), trend=trend, basis_share=share
    )
