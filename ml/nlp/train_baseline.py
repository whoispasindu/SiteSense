"""Baseline issue classifier: TF-IDF (word and character n-grams) with logistic regression.

    python -m nlp.generate && python -m nlp.train_baseline

Two models: category (8 classes) and severity (3 classes). Settings are chosen on the validation set
only; the hand-written test set is scored once at the end. Writes metrics to
models/report-nlp/baseline-metrics.json and, with --export, the model as JSON for the backend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.pipeline import FeatureUnion, Pipeline

from nlp import rules

HERE = Path(__file__).parent
DATA = HERE / "data"
REPORTS = HERE.parent / "models" / "report-nlp"
BACKEND_MODELS = HERE.parent.parent / "backend" / "app" / "ai" / "nlp" / "models"
VERSION = "1.0.0"
CATEGORIES = ["material_delay", "labour", "weather", "equipment", "safety", "design", "quality", "other"]
SEVERITIES = ["low", "medium", "high"]
WORD = {"analyzer": "word", "ngram_range": (1, 2), "lowercase": True, "sublinear_tf": True, "min_df": 1}
CHAR = {"analyzer": "char_wb", "ngram_range": (2, 5), "lowercase": True, "sublinear_tf": True, "min_df": 2}
GRID = [
    {"features": features, "c": c, "char_max": char_max, "balanced": balanced}
    for features in ("word", "char", "both")
    for c in (1.0, 4.0, 16.0)
    for char_max in (4000, 12000)
    for balanced in (False, True)
    if not (features == "word" and char_max != 4000)
]


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA / name)


def pipeline(features: str, c: float, char_max: int, balanced: bool = False) -> Pipeline:
    parts = []
    if features in ("word", "both"):
        parts.append(("word", TfidfVectorizer(**WORD)))
    if features in ("char", "both"):
        parts.append(("char", TfidfVectorizer(**CHAR, max_features=char_max)))
    return Pipeline(
        [
            ("tfidf", FeatureUnion(parts)),
            ("lr", LogisticRegression(C=c, max_iter=3000, class_weight="balanced" if balanced else None)),
        ]
    )


def macro_f1(y: Any, pred: Any, labels: list[str]) -> float:
    return float(f1_score(y, pred, labels=labels, average="macro"))


def tune(
    train: pd.DataFrame, val: pd.DataFrame, target: str, labels: list[str]
) -> tuple[dict[str, Any], float]:
    best: tuple[dict[str, Any], float] | None = None
    for settings in GRID:
        model = pipeline(**settings).fit(train.text, train[target])
        score = macro_f1(val[target], model.predict(val.text), labels)
        if best is None or score > best[1]:
            best = (settings, score)
    assert best is not None
    return best


def evaluate(model: Pipeline, test: pd.DataFrame, target: str, labels: list[str]) -> dict[str, Any]:
    return evaluate_predictions(test[target], model.predict(test.text), labels)


def evaluate_predictions(y: Any, predicted: Any, labels: list[str]) -> dict[str, Any]:
    """Per-class precision, recall and F1, macro F1, accuracy and the confusion matrix."""
    y, pred = np.asarray(list(y)), np.asarray(list(predicted))
    report = classification_report(y, pred, labels=labels, output_dict=True, zero_division=0)
    return {
        "macro_f1": round(macro_f1(y, pred, labels), 3),
        "accuracy": round(float((pred == y).mean()), 3),
        "per_class": {
            label: {
                k: round(float(report[label][k]), 3) for k in ("precision", "recall", "f1-score", "support")
            }
            for label in labels
        },
        "confusion_matrix": {
            "labels": labels,
            "rows_true_cols_predicted": confusion_matrix(y, pred, labels=labels).tolist(),
        },
    }


def export_vectorizer(vectorizer: TfidfVectorizer) -> dict[str, Any]:
    vocabulary = sorted(vectorizer.vocabulary_.items(), key=lambda item: item[1])
    return {
        "analyzer": vectorizer.analyzer,
        "ngram_range": list(vectorizer.ngram_range),
        "terms": [term for term, _ in vocabulary],
        "idf": [round(float(v), 6) for v in vectorizer.idf_],
    }


def export(model: Pipeline, labels: list[str]) -> dict[str, Any]:
    union: FeatureUnion = model.named_steps["tfidf"]
    lr: LogisticRegression = model.named_steps["lr"]
    if list(lr.classes_) != sorted(labels):
        raise ValueError("Unexpected class order")
    return {
        "vectorizers": [export_vectorizer(v) for _, v in union.transformer_list],
        "classes": list(lr.classes_),
        "coef": [[round(float(w), 6) for w in row] for row in lr.coef_],
        "intercept": [round(float(b), 6) for b in lr.intercept_],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and evaluate the TF-IDF baseline")
    parser.add_argument("--export", action="store_true", help="write the backend model file")
    args = parser.parse_args(argv)

    train, val, test = load("train.csv"), load("val.csv"), load("test_handwritten.csv")
    results: dict[str, Any] = {"model": "tfidf-logreg", "version": VERSION}
    models: dict[str, Pipeline] = {}
    for target, labels in (("category", CATEGORIES), ("severity", SEVERITIES)):
        settings, val_score = tune(train, val, target, labels)
        # Refit on train + validation with the chosen settings, then score the test set once.
        model = pipeline(**settings).fit(
            pd.concat([train.text, val.text]), pd.concat([train[target], val[target]])
        )
        models[target] = model
        results[target] = {
            "settings": settings,
            "val_macro_f1": round(val_score, 3),
            "test": evaluate(model, test, target, labels),
        }
        print(f"{target}: {settings} val {val_score:.3f} test macro F1 {results[target]['test']['macro_f1']}")

    # The labelling guide's severity rules around the severity model (model-agnostic; see rules.py).
    # Judged on validation with a model trained on train only, then reported on the test set.
    sev_settings = results["severity"]["settings"]
    train_only = pipeline(**sev_settings).fit(train.text, train.severity)
    val_rules = [rules.severity(t, lambda x: train_only.predict([x])[0]) for t in val.text]
    test_rules = [rules.severity(t, lambda x: models["severity"].predict([x])[0]) for t in test.text]
    results["severity"]["val_macro_f1_with_rules"] = round(
        macro_f1(val.severity, np.array(val_rules), SEVERITIES), 3
    )
    results["severity"]["test_with_rules"] = evaluate_predictions(test.severity, test_rules, SEVERITIES)
    print(
        f"severity with the guide's rules: val {results['severity']['val_macro_f1_with_rules']} "
        f"test {results['severity']['test_with_rules']['macro_f1']}"
    )

    REPORTS.mkdir(parents=True, exist_ok=True)
    data_hash = hashlib.sha256(
        b"".join((DATA / n).read_bytes() for n in ("train.csv", "val.csv", "test_handwritten.csv"))
    ).hexdigest()
    results.update(
        {
            "trained_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "data_sha256": data_hash,
            "rows": {"train": len(train), "val": len(val), "test": len(test)},
        }
    )
    (REPORTS / "baseline-metrics.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    if args.export:
        golden_text = list(test.text.sample(30, random_state=1))
        document = {
            "format": "sitesense-textclf-v1",
            "name": "report-issues",
            "version": VERSION,
            "trained_at": results["trained_at"],
            "models": {
                target: export(models[target], labels)
                for target, labels in (("category", CATEGORIES), ("severity", SEVERITIES))
            },
            "training": {
                "data": "synthetic train/val (ml/nlp/generate.py); hand-written test set",
                "data_sha256": data_hash,
            },
            "metrics": {t: results[t]["test"]["macro_f1"] for t in ("category", "severity")},
            "golden": [
                {
                    "text": text,
                    **{
                        t: [round(float(p), 9) for p in models[t].predict_proba([text])[0]]
                        for t in ("category", "severity")
                    },
                }
                for text in golden_text
            ],
        }
        BACKEND_MODELS.mkdir(parents=True, exist_ok=True)
        path = BACKEND_MODELS / f"report-issues-v{VERSION}.json"
        path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
        print(f"Model: {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
