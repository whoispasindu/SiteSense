"""The supplier delivery generator and on-time model (BR-12): reproducible, no peeking, same as the app."""

import importlib.util
import json
import math
import sys
from datetime import date
from pathlib import Path

import pytest

from data_generator import deliveries

BACKEND = Path(__file__).parents[2] / "backend" / "app" / "ai" / "supplier"


def backend_model():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("backend_supplier_model", BACKEND / "model.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["backend_supplier_model"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rows() -> list[dict[str, object]]:
    return deliveries.generate(20, seed=3)


def test_same_seed_same_histories(rows: list[dict[str, object]]) -> None:
    assert deliveries.generate(20, seed=3) == rows
    assert deliveries.generate(20, seed=4) != rows


def test_features_use_only_orders_already_due(rows: list[dict[str, object]]) -> None:
    """A supplier's record at an order counts only its orders whose expected date had passed."""
    for row in rows:
        placed = date.fromisoformat(str(row["placed"]))
        earlier_due = sum(
            1
            for other in rows
            if other["supplier_id"] == row["supplier_id"]
            and date.fromisoformat(str(other["expected"])) < placed
        )
        assert row["prior_deliveries"] == earlier_due


def test_every_row_is_finite_and_labelled(rows: list[dict[str, object]]) -> None:
    for row in rows:
        assert all(math.isfinite(float(row[f])) for f in deliveries.FEATURES)  # type: ignore[arg-type]
        assert row["on_time"] in (0, 1)
        assert 0 <= float(row["wet_share"]) <= 1  # type: ignore[arg-type]


def test_the_backend_computes_the_same_inputs() -> None:
    model = backend_model().load(BACKEND / "models" / "supplier-v1.0.0.json")
    cases = [
        (0, 0, 0, 0, 14, 0.1),
        (3, 4, 50, 80, 2, 0.4),
        (40, 60, 900, 1200, 30, 0.0),
        (0, 2, 10, 10, 0, 0.2),
    ]
    for own_on, own_n, co_on, co_n, lead, wet in cases:
        mine = deliveries.features(own_on, own_n, co_on, co_n, lead, wet)
        theirs = model.inputs(supplier_on_time=own_on, supplier_count=own_n, company_on_time=co_on,
                              company_count=co_n, lead_time_days=lead, wet_share=wet)  # fmt: skip
        assert theirs == pytest.approx(mine, abs=1e-12)


def test_the_shipped_model_matches_its_metrics_and_constants() -> None:
    shipped = json.loads((BACKEND / "models" / "supplier-v1.0.0.json").read_text(encoding="utf-8"))
    metrics = json.loads(
        (Path(__file__).parents[1] / "models" / "supplier-v1.0.0" / "metrics.json").read_text(
            encoding="utf-8"
        )
    )

    assert shipped["kind"] == metrics["shipped"]
    assert shipped["constants"]["prior_strength"] == deliveries.PRIOR_STRENGTH
    assert shipped["constants"]["default_rate"] == deliveries.DEFAULT_RATE
    # The rule: logistic ships only when the whole interval favours it.
    interval = metrics["choice"]["logistic_minus_baseline_log_loss"]
    assert (shipped["kind"] == "logistic") == (interval["high"] < 0)
