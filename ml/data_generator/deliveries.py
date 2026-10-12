"""Synthetic supplier delivery histories, for the supplier on-time model (BR-12, Phase 10).

    python -m data_generator.deliveries            # writes data/deliveries.csv

The app has almost no delivery history yet, so the model is trained on simulated suppliers. Every
assumption is written down here and in ``ASSUMPTIONS.md``; the rain climate is the real one
(``simulate.heavy_rain_climate`` over ``rainfall.csv``), the same table the backend uses.

How a supplier is simulated
    Each supplier has a hidden base on-time chance (most are fairly reliable, a tail is not) and a
    hidden sensitivity to the wet season. An order is on time with a chance that falls in months with
    more heavy-rain days at the site's town, and when the lead time is short. Orders arrive over the
    years; some suppliers have hundreds, many only a handful.

What the app would know at each order (the features)
    Only the supplier's orders already due before this one was placed (an order is known to be on
    time or late once its expected date has passed), and the company's record across all suppliers.
    Nothing from the future, and never the hidden values.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from data_generator.simulate import heavy_rain_climate, load_rainfall

OUTPUT = Path(__file__).parents[1] / "data" / "deliveries.csv"

# --- Shared definitions (mirrored in backend/app/ai/supplier/features.py) ------------------------------

PRIOR_STRENGTH = 5.0  # a supplier's record is smoothed towards the company's as if by 5 average deliveries
DEFAULT_RATE = 0.8  # the company's on-time share before it has a record of its own
COMPANY_PRIOR_STRENGTH = 20.0  # the company's own share is smoothed towards DEFAULT_RATE like this
SHORT_LEAD_DAYS = 7  # lead times under a week are "short"
FEATURES = ("supplier_logit", "log_deliveries", "lead_time_days", "wet_share", "short_lead")

# --- Simulation assumptions (ASSUMPTIONS.md, "Suppliers") ---------------------------------------------

WET_EFFECT = 1.5  # log-odds lost per unit of heavy-rain share, scaled by the supplier's sensitivity
SHORT_LEAD_EFFECT = 0.6  # log-odds lost at a lead time of zero, falling to none at a week
LEAD_TIMES = (2, 3, 5, 7, 10, 14, 21, 30)
LEAD_WEIGHTS = (0.06, 0.08, 0.12, 0.18, 0.18, 0.18, 0.12, 0.08)
FIRST_ORDER, LAST_ORDER = date(2016, 1, 4), date(2025, 6, 30)


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def smoothed(on_time: float, count: float, prior: float, strength: float) -> float:
    """An on-time share pulled towards ``prior`` as if by ``strength`` extra deliveries at that rate."""
    return (on_time + strength * prior) / (count + strength)


def company_prior(on_time: float, count: float) -> float:
    return smoothed(on_time, count, DEFAULT_RATE, COMPANY_PRIOR_STRENGTH)


def features(
    supplier_on_time: float, supplier_count: float, company_on_time: float, company_count: float,
    lead_time_days: float, wet_share: float,
) -> dict[str, float]:  # fmt: skip
    """The model's inputs for one order, from what the app knows when the order is placed."""
    rate = smoothed(
        supplier_on_time, supplier_count, company_prior(company_on_time, company_count), PRIOR_STRENGTH
    )
    lead = min(max(lead_time_days, 0.0), 120.0)
    return {
        "supplier_logit": logit(rate),
        "log_deliveries": math.log1p(supplier_count),
        "lead_time_days": lead,
        "wet_share": wet_share,
        "short_lead": max(0.0, SHORT_LEAD_DAYS - lead) / SHORT_LEAD_DAYS,
    }


@dataclass
class Order:
    supplier: int
    placed: date
    expected: date
    town: str
    on_time: bool


def generate(n_suppliers: int, seed: int) -> list[dict[str, object]]:
    rng = np.random.default_rng(seed)
    rainfall = load_rainfall()
    towns = sorted(rainfall)
    climate = {t: heavy_rain_climate(s) for t, s in rainfall.items()}
    span = (LAST_ORDER - FIRST_ORDER).days

    orders: list[Order] = []
    for supplier in range(1, n_suppliers + 1):
        base = float(np.clip(rng.beta(6, 2) * 1.05, 0.2, 0.98))  # hidden: most suppliers are fairly reliable
        sensitivity = float(rng.uniform(0.5, 1.5))  # hidden: how badly the wet season hits them
        count = int(np.clip(round(rng.lognormal(math.log(18), 1.0)), 1, 300))  # many have only a few orders
        for _ in range(count):
            placed = FIRST_ORDER + timedelta(days=int(rng.integers(0, span)))
            lead = int(rng.choice(LEAD_TIMES, p=LEAD_WEIGHTS))
            expected = placed + timedelta(days=lead)
            town = str(rng.choice(towns))
            wet = climate[town][expected.month]
            short = max(0.0, SHORT_LEAD_DAYS - lead) / SHORT_LEAD_DAYS
            chance = sigmoid(logit(base) - WET_EFFECT * sensitivity * wet - SHORT_LEAD_EFFECT * short)
            orders.append(Order(supplier, placed, expected, town, bool(rng.random() < chance)))

    # Features from what was known when each order was placed: orders due before that day.
    orders.sort(key=lambda o: (o.placed, o.supplier))
    due = sorted(orders, key=lambda o: o.expected)
    company = [0.0, 0.0]  # on time, count
    by_supplier: dict[int, list[float]] = {}
    rows: list[dict[str, object]] = []
    i = 0
    for order in orders:
        while i < len(due) and due[i].expected < order.placed:
            known = due[i]
            company[0] += known.on_time
            company[1] += 1
            record = by_supplier.setdefault(known.supplier, [0.0, 0.0])
            record[0] += known.on_time
            record[1] += 1
            i += 1
        own = by_supplier.get(order.supplier, [0.0, 0.0])
        x = features(own[0], own[1], company[0], company[1], (order.expected - order.placed).days,
                     climate[order.town][order.expected.month])  # fmt: skip
        rows.append(
            {
                "supplier_id": order.supplier,
                "placed": order.placed.isoformat(),
                "expected": order.expected.isoformat(),
                "town": order.town,
                "prior_deliveries": int(own[1]),
                **{k: round(v, 6) for k, v in x.items()},
                "on_time": int(order.on_time),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--suppliers", type=int, default=150)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    rows = generate(args.suppliers, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    on_time = sum(int(r["on_time"]) for r in rows) / len(rows)  # type: ignore[call-overload]
    print(
        f"Wrote {len(rows)} orders from {args.suppliers} suppliers ({on_time:.0%} on time) to {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
