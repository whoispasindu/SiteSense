"""How much does rain's weight in the risk model depend on the assumed rain allowance?

    python rain_sensitivity.py

``RAIN_ALLOWANCE`` (the share of a town's usual rain loss that programmes allow for) is an
assumption, not measured data (see ``data_generator/ASSUMPTIONS.md``). This script simulates the
projects again with the alternative allowance, recalibrates the pace so the median project is still
10% late, trains with exactly the same code as the shipped model, and writes both sets of results
side by side to ``models/risk-v<version>/rain-sensitivity.json``. Nothing it trains is shipped.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pandas as pd

import train
from data_generator import simulate

ALTERNATIVE_ALLOWANCE = 0.75
RAIN_FEATURES = ("rain_days_next_14", "wet_days_ahead")


def summary(report: dict[str, Any], rows: pd.DataFrame, allowance: float, pace: float) -> dict[str, Any]:
    finals = rows.groupby("project_id").first()
    bands = finals["final_score"].map(train.band).value_counts(normalize=True)
    delay = report["targets"]["delay_days"]
    overrun = report["targets"]["overrun_pct"]
    return {
        "rain_allowance": allowance,
        "base_pace": pace,
        "median_delay_pct_of_plan": round(
            float((100 * finals.delay_days / finals.planned_duration_days).median()), 1
        ),
        "final_bands": {b: round(float(bands.get(b, 0.0)), 3) for b in train.BANDS},
        "delay_rain_gain_pct": {f: delay["importance_gain_pct"].get(f, 0.0) for f in RAIN_FEATURES},
        "overrun_rain_gain_pct": {f: overrun["importance_gain_pct"].get(f, 0.0) for f in RAIN_FEATURES},
        "delay_test": delay["test"],
        "overrun_test": overrun["test"],
        "f1_high": report["risk_class"]["f1_high"],
    }


def main() -> int:
    shipped_dir = train.ML / "models" / f"risk-v{train.VERSION}"
    shipped = json.loads((shipped_dir / "metrics.json").read_text(encoding="utf-8"))
    rainfall = simulate.load_rainfall()

    saved = simulate.RAIN_ALLOWANCE, simulate.BASE_PACE
    try:
        simulate.RAIN_ALLOWANCE = ALTERNATIVE_ALLOWANCE
        simulate.BASE_PACE = simulate.calibrate_pace(300, 2026, rainfall)
        rows = pd.DataFrame(simulate.generate(300, 2026, rainfall))
        _, report, _ = train.train_and_evaluate(rows)
        alternative = summary(report, rows, ALTERNATIVE_ALLOWANCE, simulate.BASE_PACE)
    finally:
        simulate.RAIN_ALLOWANCE, simulate.BASE_PACE = saved

    shipped_rows = pd.read_csv(train.DATA)
    result = {
        "question": "How much does rain's weight depend on RAIN_ALLOWANCE, an assumption?",
        "shipped": summary(shipped, shipped_rows, simulate.RAIN_ALLOWANCE, simulate.BASE_PACE),
        "alternative": alternative,
    }
    out = shipped_dir / "rain-sensitivity.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
