"""Train risk model v1: final delay (days) and cost overrun (%) from weekly project snapshots.

    python -m data_generator.simulate      # writes data/snapshots.csv
    python train.py                        # trains, evaluates, exports

Method
    - Train/test split grouped by project (no project has weeks on both sides, so nothing leaks).
    - Baseline: linear regression on the same features.
    - Main model: LightGBM gradient boosting, tuned with 5-fold cross-validation grouped by project,
      with monotone constraints where the direction is known (falling further behind can only raise
      the predicted delay), so the model cannot learn a backwards rule from noise.
    - Metrics on the held-out projects: MAE, RMSE and R squared for both targets, F1 for the High
      class (from the risk score), and a backtest of how early High projects were flagged.

Export
    The backend does not load pickles (joblib/pickle files run code when loaded). The trees are
    exported as plain JSON (``backend/app/ai/risk/models/risk-v<version>.json``) and evaluated by a
    small pure-Python scorer, with golden predictions from LightGBM itself so a backend test proves
    the two agree. Metrics and settings go to ``models/risk-v<version>/metrics.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import confusion_matrix, f1_score, mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from data_generator.simulate import FEATURES, TARGETS, risk_score

ML = Path(__file__).parent
DATA = ML / "data" / "snapshots.csv"
BACKEND_MODELS = ML.parent / "backend" / "app" / "ai" / "risk" / "models"
VERSION = "1.2.0"
SEED = 2026
BANDS = ("low", "medium", "high")

# +1: a higher value can only raise the prediction; -1: can only lower it; 0: learnt freely.
MONOTONE: dict[str, dict[str, int]] = {
    "delay_days": {
        "progress_gap_pct": -1,
        "progress_rate_trend": -1,
        "late_deliveries_count": 1,
        "avg_lateness_days": 1,
        "rain_days_next_14": 1,
        "wet_days_ahead": 1,
        "crew_vs_plan_pct": -1,
        "missing_reports_14": 1,
        "issues_material_14": 1,
        "issues_safety_14": 1,
        "issues_design_14": 1,
    },
    "overrun_pct": {
        "progress_gap_pct": -1,
        "budget_variance_pct": 1,
        "wet_days_ahead": 1,
        "late_deliveries_count": 1,
        "avg_lateness_days": 1,
        "issues_design_14": 1,
    },
}
BASE_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "learning_rate": 0.05,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "use_missing": False,  # the feature builder always supplies numbers; keeps the exported trees simple
    "zero_as_missing": False,
    "deterministic": True,
    "force_row_wise": True,
    "seed": SEED,
    "verbose": -1,
}
GRID = [{"num_leaves": n, "min_child_samples": m} for n in (7, 15, 31) for m in (40, 100)]


def band(score: int) -> str:
    return "high" if score >= 70 else "medium" if score >= 40 else "low"


def scores(delay: np.ndarray, overrun: np.ndarray, planned_days: np.ndarray) -> np.ndarray:
    return np.array([risk_score(d, o, p) for d, o, p in zip(delay, overrun, planned_days, strict=True)])


def regression_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    return {
        "mae": round(float(mean_absolute_error(y, pred)), 2),
        "rmse": round(float(np.sqrt(mean_squared_error(y, pred))), 2),
        "r2": round(float(r2_score(y, pred)), 3),
    }


def tune(x: pd.DataFrame, y: pd.Series, groups: pd.Series, target: str) -> tuple[dict[str, Any], int, float]:
    """Pick tree size and rounds by 5-fold cross-validation grouped by project."""
    folds = list(GroupKFold(n_splits=5).split(x, y, groups))
    monotone = [MONOTONE[target].get(f, 0) for f in FEATURES]
    best: tuple[dict[str, Any], int, float] | None = None
    for extra in GRID:
        params = {**BASE_PARAMS, **extra, "monotone_constraints": monotone, "metric": "rmse"}
        result = lgb.cv(
            params,
            lgb.Dataset(x, y, free_raw_data=False),
            num_boost_round=2000,
            folds=folds,
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )
        rmse = result["valid rmse-mean"][-1]
        rounds = len(result["valid rmse-mean"])
        print(f"  {target} {extra}: cv rmse {rmse:.3f} at {rounds} rounds")
        if best is None or rmse < best[2]:
            best = (params, rounds, rmse)
    assert best is not None
    return best


def export_tree(node: dict[str, Any], nodes: list[list[float]]) -> int:
    """Flatten a LightGBM tree into rows [feature, threshold, left, right, value]; leaves have feature -1."""
    index = len(nodes)
    if "leaf_value" in node:
        nodes.append([-1, 0.0, -1, -1, float(node["leaf_value"])])
        return index
    if node["decision_type"] != "<=" or node["missing_type"] != "None":
        raise ValueError(f"Unsupported split: {node['decision_type']} / {node['missing_type']}")
    nodes.append(
        [int(node["split_feature"]), float(node["threshold"]), -1, -1, float(node["internal_value"])]
    )
    nodes[index][2] = export_tree(node["left_child"], nodes)
    nodes[index][3] = export_tree(node["right_child"], nodes)
    return index


def export_model(booster: lgb.Booster) -> list[list[list[float]]]:
    dump = booster.dump_model()
    if dump["feature_names"] != list(FEATURES):
        raise ValueError("Feature order changed between training and export")
    trees = []
    for info in dump["tree_info"]:
        nodes: list[list[float]] = []
        export_tree(info["tree_structure"], nodes)
        trees.append(nodes)
    return trees


def backtest(test: pd.DataFrame, predicted: np.ndarray) -> dict[str, Any]:
    """How early were projects that ended High flagged High, and how often were Low projects flagged?"""
    frame = test.assign(predicted=predicted)
    flagged_at: list[float] = []
    lead_weeks: list[float] = []
    missed = 0
    false_alarms = 0
    lows = 0
    for _, weeks in frame.groupby("project_id"):
        weeks = weeks.sort_values("snapshot_date")
        final = band(int(weeks["final_score"].iloc[0]))
        hits = weeks[weeks["predicted"] >= 70]
        if final == "high":
            if hits.empty:
                missed += 1
            else:
                first = hits.iloc[0]
                flagged_at.append(float(first["elapsed_pct"]))
                lead_weeks.append(
                    float(first["planned_duration_days"] * (1 - first["elapsed_pct"] / 100) / 7)
                )
        elif final == "low":
            lows += 1
            false_alarms += int(not hits.empty)
    return {
        "high_projects": len(flagged_at) + missed,
        "flagged": len(flagged_at),
        "median_flagged_at_elapsed_pct": round(float(np.median(flagged_at)), 1) if flagged_at else None,
        "median_weeks_before_planned_end": round(float(np.median(lead_weeks)), 1) if lead_weeks else None,
        "low_projects": lows,
        "low_projects_ever_flagged_high": false_alarms,
    }


def train_and_evaluate(data: pd.DataFrame) -> tuple[dict[str, lgb.Booster], dict[str, Any], pd.DataFrame]:
    """Grouped split, tuning, training and every held-out metric: the boosters, the report, the test rows."""
    split = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED)
    train_idx, test_idx = next(split.split(data, groups=data["project_id"]))
    train, test = data.iloc[train_idx], data.iloc[test_idx]
    x_train, x_test = train[list(FEATURES)], test[list(FEATURES)]
    print(
        f"{len(train)} training rows ({train.project_id.nunique()} projects), "
        f"{len(test)} test rows ({test.project_id.nunique()} projects)"
    )

    boosters: dict[str, lgb.Booster] = {}
    report: dict[str, Any] = {"targets": {}}
    predictions: dict[str, np.ndarray] = {}
    baseline_predictions: dict[str, np.ndarray] = {}
    for target in TARGETS:
        params, rounds, cv_rmse = tune(x_train, train[target], train["project_id"], target)
        booster = lgb.train(params, lgb.Dataset(x_train, train[target]), num_boost_round=rounds)
        boosters[target] = booster
        predictions[target] = booster.predict(x_test)
        baseline = make_pipeline(StandardScaler(), LinearRegression()).fit(x_train, train[target])
        baseline_predictions[target] = baseline.predict(x_test)
        gain = booster.feature_importance("gain")
        report["targets"][target] = {
            "params": {k: params[k] for k in ("num_leaves", "min_child_samples", "learning_rate")},
            "rounds": rounds,
            "cv_rmse": round(cv_rmse, 3),
            "test": regression_metrics(test[target].to_numpy(), predictions[target]),
            "baseline_test": regression_metrics(test[target].to_numpy(), baseline_predictions[target]),
            "importance_gain_pct": {
                f: round(float(g / gain.sum() * 100), 1)
                for f, g in sorted(zip(FEATURES, gain, strict=True), key=lambda p: -p[1])
                if g > 0
            },
        }

    planned = test["planned_duration_days"].to_numpy()
    true_bands = [band(s) for s in test["final_score"]]
    model_bands = [band(s) for s in scores(predictions["delay_days"], predictions["overrun_pct"], planned)]
    base_bands = [
        band(s)
        for s in scores(baseline_predictions["delay_days"], baseline_predictions["overrun_pct"], planned)
    ]
    model_scores = scores(predictions["delay_days"], predictions["overrun_pct"], planned)
    report["risk_class"] = {
        "f1_high": round(float(f1_score(true_bands, model_bands, labels=["high"], average="macro")), 3),
        "f1_high_baseline": round(
            float(f1_score(true_bands, base_bands, labels=["high"], average="macro")), 3
        ),
        "f1_macro": round(float(f1_score(true_bands, model_bands, labels=list(BANDS), average="macro")), 3),
        "confusion_matrix": {
            "labels": list(BANDS),
            "rows_true_cols_predicted": confusion_matrix(
                true_bands, model_bands, labels=list(BANDS)
            ).tolist(),
        },
    }
    report["backtest"] = backtest(test, model_scores)

    # Errors by stage: forecasts get better as a project runs.
    stages = pd.cut(
        test["elapsed_pct"],
        [0, 25, 50, 75, 100, 1000],
        labels=["0-25%", "25-50%", "50-75%", "75-100%", "late"],
    )
    report["delay_mae_by_elapsed"] = {
        str(stage): round(
            float(
                mean_absolute_error(
                    test["delay_days"][stages == stage], predictions["delay_days"][stages == stage]
                )
            ),
            1,
        )
        for stage in stages.cat.categories
        if (stages == stage).any()
    }
    return boosters, report, test


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and export the risk model")
    parser.add_argument("--data", type=Path, default=DATA)
    args = parser.parse_args(argv)

    data = pd.read_csv(args.data)
    data_hash = hashlib.sha256(args.data.read_bytes()).hexdigest()
    boosters, report, test = train_and_evaluate(data)
    train = data[~data.index.isin(test.index)]

    # Golden rows: LightGBM's own predictions, which the backend's JSON scorer must reproduce.
    golden_x = test.sample(25, random_state=SEED)[list(FEATURES)]
    golden_delay = boosters["delay_days"].predict(golden_x)
    golden_overrun = boosters["overrun_pct"].predict(golden_x)
    golden = [
        {"x": [float(v) for v in x], "delay_days": float(d), "overrun_pct": float(o)}
        for x, d, o in zip(golden_x.to_numpy(), golden_delay, golden_overrun, strict=True)
    ]

    trained_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    model = {
        "format": "sitesense-gbdt-v1",
        "name": "risk",
        "version": VERSION,
        "trained_at": trained_at,
        "features": list(FEATURES),
        "targets": {target: {"trees": export_model(boosters[target])} for target in TARGETS},
        "training": {
            "data": "synthetic: ml/data_generator (see ml/data_generator/ASSUMPTIONS.md)",
            "data_sha256": data_hash,
            "projects": int(data.project_id.nunique()),
            "rows": len(data),
        },
        "golden": golden,
    }
    BACKEND_MODELS.mkdir(parents=True, exist_ok=True)
    model_path = BACKEND_MODELS / f"risk-v{VERSION}.json"
    model_path.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")

    report_dir = ML / "models" / f"risk-v{VERSION}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report.update(
        {
            "version": VERSION,
            "trained_at": trained_at,
            "data_sha256": data_hash,
            "split": {
                "train_projects": int(train.project_id.nunique()),
                "test_projects": int(test.project_id.nunique()),
                "train_rows": len(train),
                "test_rows": len(test),
            },
            "model_file": str(model_path.relative_to(ML.parent)).replace("\\", "/"),
            "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        }
    )
    (report_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: report[k] for k in ("targets", "risk_class", "backtest", "delay_mae_by_elapsed")}, indent=1
        )[:6000]
    )
    print(f"Model: {model_path} ({model_path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
