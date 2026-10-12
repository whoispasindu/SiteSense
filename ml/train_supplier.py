"""Train the supplier on-time model (BR-12): a smoothed on-time rate against logistic regression.

    python -m data_generator.deliveries      # writes data/deliveries.csv
    python train_supplier.py                 # trains, evaluates, exports

Two candidates estimate the chance that a supplier's next order arrives on time:

- **baseline: the smoothed on-time rate.** The supplier's on-time share, pulled towards the company's
  as if by five average deliveries, so a supplier with two orders is not 0% or 100%.
- **logistic regression** on that rate (as log-odds), how many deliveries it rests on, the lead time,
  whether the lead time is short, and the wet season at the site.

The logistic model ships only if it is **clearly** better than the baseline on suppliers it never
saw: the 95% interval, from resampling whole suppliers, for the difference in log loss must lie
entirely in its favour. Otherwise the smoothed rate ships. Both are plain JSON for the backend.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

import risk_models as rm
from data_generator import deliveries as gen

ML = Path(__file__).parent
DATA = gen.OUTPUT
BACKEND_MODELS = ML.parent / "backend" / "app" / "ai" / "supplier" / "models"
VERSION = "1.0.0"
MODEL_FORMAT = "sitesense-supplier-v1"
SEED = 2026
LOW_DATA_DELIVERIES = 5  # fewer deliveries than this: the estimate is marked "low data"
# The logistic model also sees how much the supplier's rate should be trusted.
MODEL_FEATURES = (*gen.FEATURES, "supplier_logit_x_log_deliveries")


def design(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame[list(gen.FEATURES)].copy()
    x["supplier_logit_x_log_deliveries"] = x["supplier_logit"] * x["log_deliveries"]
    return x[list(MODEL_FEATURES)]


def baseline_p(frame: pd.DataFrame) -> np.ndarray:
    return 1 / (1 + np.exp(-frame["supplier_logit"].to_numpy(dtype=float)))


def fit_logistic(x: pd.DataFrame, y: pd.Series) -> tuple[float, np.ndarray]:
    """Logistic regression on standardised inputs, returned on the raw scale (intercept, coefficients)."""
    mean, scale = x.mean().to_numpy(), x.std(ddof=0).replace(0, 1).to_numpy()
    model = LogisticRegression(C=1.0, max_iter=1000).fit((x.to_numpy() - mean) / scale, y)
    coef = model.coef_[0] / scale
    return float(model.intercept_[0] - (coef * mean).sum()), coef


def logistic_p(intercept: float, coef: np.ndarray, x: pd.DataFrame) -> np.ndarray:
    return 1 / (1 + np.exp(-(intercept + x.to_numpy() @ coef)))


def row_log_loss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {
        "log_loss": round(float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6))), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "auc": round(float(roc_auc_score(y, p)), 3),
    }


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 5) -> list[dict[str, float]]:
    """Predicted against actual on-time share, by bands of the prediction."""
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    out = []
    for lo, hi in itertools.pairwise(edges):
        mask = (p >= lo) & (p <= hi)
        if mask.any():
            out.append(
                {
                    "predicted": round(float(p[mask].mean()), 3),
                    "actual": round(float(y[mask].mean()), 3),
                    "orders": int(mask.sum()),
                }
            )
    return out


def main() -> int:
    data = pd.read_csv(DATA)
    data_hash = hashlib.sha256(DATA.read_bytes()).hexdigest()
    split = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED)
    train_idx, test_idx = next(split.split(data, groups=data["supplier_id"]))
    train, test = data.iloc[train_idx], data.iloc[test_idx]
    y_train, y_test = train["on_time"], test["on_time"].to_numpy()

    # The choice, on suppliers left out by grouped cross-validation within the training suppliers.
    oof = np.empty(len(train))
    for a, b in GroupKFold(n_splits=5).split(train, y_train, train["supplier_id"]):
        intercept, coef = fit_logistic(design(train.iloc[a]), y_train.iloc[a])
        oof[b] = logistic_p(intercept, coef, design(train.iloc[b]))
    truth = y_train.to_numpy()
    difference = rm.error_difference(
        row_log_loss(truth, oof), row_log_loss(truth, baseline_p(train)), train["supplier_id"]
    )
    kind = "logistic" if rm.clearly_better(difference) else "smoothed"

    intercept, coef = fit_logistic(design(train), y_train)
    p_logistic = logistic_p(intercept, coef, design(test))
    p_baseline = baseline_p(test)
    shipped = p_logistic if kind == "logistic" else p_baseline
    low = test["prior_deliveries"].to_numpy() < LOW_DATA_DELIVERIES
    report: dict[str, Any] = {
        "version": VERSION,
        "shipped": kind,
        "choice": {
            "logistic_minus_baseline_log_loss": difference,
            "rule": "logistic only if the whole 95% interval is below zero",
        },
        "test": {"logistic": metrics(y_test, p_logistic), "smoothed": metrics(y_test, p_baseline)},
        "test_by_history": {
            "low_data": {"orders": int(low.sum()), **metrics(y_test[low], shipped[low])},
            "enough_data": {"orders": int((~low).sum()), **metrics(y_test[~low], shipped[~low])},
        },
        "calibration": calibration(y_test, shipped),
        "coefficients": dict(zip(MODEL_FEATURES, (round(float(c), 4) for c in coef), strict=True)),
        "split": {
            "train_suppliers": int(train.supplier_id.nunique()),
            "test_suppliers": int(test.supplier_id.nunique()),
            "train_orders": len(train),
            "test_orders": len(test),
        },
        "on_time_share": round(float(data["on_time"].mean()), 3),
        "data_sha256": data_hash,
    }

    golden_rows = test.sample(25, random_state=SEED)
    golden_p = (
        logistic_p(intercept, coef, design(golden_rows)) if kind == "logistic" else baseline_p(golden_rows)
    )
    trained_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    model = {
        "format": MODEL_FORMAT,
        "name": "supplier",
        "version": VERSION,
        "trained_at": trained_at,
        "kind": kind,
        "features": list(MODEL_FEATURES),
        "intercept": intercept,
        "coef": [float(c) for c in coef],
        "constants": {
            "prior_strength": gen.PRIOR_STRENGTH,
            "default_rate": gen.DEFAULT_RATE,
            "company_prior_strength": gen.COMPANY_PRIOR_STRENGTH,
            "short_lead_days": gen.SHORT_LEAD_DAYS,
            "low_data_deliveries": LOW_DATA_DELIVERIES,
        },
        "training": {
            "data": "synthetic: ml/data_generator/deliveries.py (see ml/data_generator/ASSUMPTIONS.md)",
            "data_sha256": data_hash,
            "suppliers": int(data.supplier_id.nunique()),
            "orders": len(data),
        },
        "golden": [
            {"inputs": {f: float(r[f]) for f in gen.FEATURES}, "p": float(p)}
            for (_, r), p in zip(golden_rows.iterrows(), golden_p, strict=True)
        ],
    }
    BACKEND_MODELS.mkdir(parents=True, exist_ok=True)
    model_path = BACKEND_MODELS / f"supplier-v{VERSION}.json"
    model_path.write_text(json.dumps(model, indent=1) + "\n", encoding="utf-8")
    report_dir = ML / "models" / f"supplier-v{VERSION}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report["trained_at"] = trained_at
    report["model_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    (report_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("shipped", "choice", "test", "test_by_history", "calibration", "coefficients")
            },
            indent=1,
        )
    )
    if not math.isfinite(intercept):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
