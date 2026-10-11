"""Load the report issue classifier (JSON) and score sentences in pure Python.

The classifier is trained in ``ml/nlp/train_baseline.py`` (scikit-learn TF-IDF + logistic regression)
and exported as plain JSON: for each target (category, severity) the vectorizers' terms and IDF
weights, the classes, and the coefficients. As with the risk model, nothing is unpickled (ADR 0009):
the file is validated and then read as data.

Scoring reproduces scikit-learn exactly: lower-case; word n-grams over ``\\b\\w\\w+\\b`` tokens, or
character n-grams within word boundaries padded with spaces (``char_wb``); sublinear term frequency
(1 + ln tf) times IDF; each vectorizer's vector L2-normalised; then softmax over the linear scores.
Golden probabilities from scikit-learn in the model file prove the two agree.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

MODELS_DIR = Path(__file__).parent / "models"
MODEL_FORMAT = "sitesense-textclf-v1"
CURRENT_VERSION = "1.0.0"
MAX_TERMS = 200_000
_TOKEN = re.compile(r"(?u)\b\w\w+\b")
_SPACES = re.compile(r"\s\s+")


class TextModelError(ValueError):
    """The model file is missing or not a valid SiteSense text classifier."""


@dataclass(frozen=True, slots=True)
class Vectorizer:
    analyzer: str  # "word" or "char_wb"
    low: int
    high: int
    index: dict[str, int]
    idf: tuple[float, ...]

    def grams(self, text: str) -> list[str]:
        text = text.lower()
        if self.analyzer == "word":
            tokens = _TOKEN.findall(text)
            grams = list(tokens) if self.low == 1 else []
            for n in range(max(self.low, 2), min(self.high, len(tokens)) + 1):
                grams.extend(" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1))
            return grams
        grams = []
        for word in _SPACES.sub(" ", text).split():
            padded = f" {word} "
            for n in range(self.low, self.high + 1):
                offset = 0
                grams.append(padded[offset : offset + n])
                while offset + n < len(padded):
                    offset += 1
                    grams.append(padded[offset : offset + n])
                if offset == 0:  # a word shorter than n is counted once
                    break
        return grams

    def vector(self, text: str) -> dict[int, float]:
        counts = Counter(i for g in self.grams(text) if (i := self.index.get(g)) is not None)
        weights = {i: (1.0 + math.log(tf)) * self.idf[i] for i, tf in counts.items()}
        norm = math.sqrt(sum(w * w for w in weights.values()))
        return {i: w / norm for i, w in weights.items()} if norm else {}


@dataclass(frozen=True, slots=True)
class Classifier:
    vectorizers: tuple[Vectorizer, ...]
    classes: tuple[str, ...]
    coef: tuple[tuple[float, ...], ...]
    intercept: tuple[float, ...]

    def probabilities(self, text: str) -> dict[str, float]:
        features: dict[int, float] = {}
        offset = 0
        for vectorizer in self.vectorizers:
            for i, w in vectorizer.vector(text).items():
                features[offset + i] = w
            offset += len(vectorizer.idf)
        scores = [
            b + sum(row[i] * w for i, w in features.items())
            for row, b in zip(self.coef, self.intercept, strict=True)
        ]
        top = max(scores)
        exps = [math.exp(s - top) for s in scores]
        total = sum(exps)
        return {c: e / total for c, e in zip(self.classes, exps, strict=True)}


@dataclass(frozen=True, slots=True)
class TextModel:
    version: str
    category: Classifier
    severity: Classifier
    metrics: dict[str, Any]
    golden: tuple[dict[str, Any], ...]


def _vectorizer(raw: Any) -> Vectorizer:
    if not isinstance(raw, dict) or raw.get("analyzer") not in ("word", "char_wb"):
        raise TextModelError("Unknown vectorizer.")
    low, high = raw.get("ngram_range", [None, None])
    terms, idf = raw.get("terms"), raw.get("idf")
    if not (isinstance(low, int) and isinstance(high, int) and 1 <= low <= high <= 8):
        raise TextModelError("Bad n-gram range.")
    if not (isinstance(terms, list) and isinstance(idf, list) and 0 < len(terms) == len(idf) <= MAX_TERMS):
        raise TextModelError("Terms and IDF weights must be lists of the same length.")
    if not all(isinstance(t, str) for t in terms) or len(set(terms)) != len(terms):
        raise TextModelError("Terms must be unique strings.")
    if not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0 for v in idf
    ):
        raise TextModelError("IDF weights must be positive numbers.")
    return Vectorizer(
        raw["analyzer"], low, high, {t: i for i, t in enumerate(terms)}, tuple(float(v) for v in idf)
    )


def _classifier(raw: Any, expected: set[str]) -> Classifier:
    if not isinstance(raw, dict):
        raise TextModelError("A classifier must be an object.")
    vectorizers = tuple(_vectorizer(v) for v in raw.get("vectorizers", []))
    classes, coef, intercept = raw.get("classes"), raw.get("coef"), raw.get("intercept")
    if not vectorizers:
        raise TextModelError("A classifier needs at least one vectorizer.")
    if not (isinstance(classes, list) and set(classes) == expected and len(classes) == len(expected)):
        raise TextModelError(f"Classes must be exactly {sorted(expected)}.")
    width = sum(len(v.idf) for v in vectorizers)
    if not (
        isinstance(coef, list)
        and len(coef) == len(classes)
        and all(isinstance(r, list) and len(r) == width for r in coef)
    ):
        raise TextModelError("Coefficients do not match the classes and features.")
    if not (isinstance(intercept, list) and len(intercept) == len(classes)):
        raise TextModelError("One intercept per class is needed.")
    numbers = [x for row in coef for x in row] + intercept
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in numbers):
        raise TextModelError("Coefficients must be finite numbers.")
    return Classifier(
        vectorizers,
        tuple(classes),
        tuple(tuple(float(x) for x in row) for row in coef),
        tuple(float(x) for x in intercept),
    )


CATEGORIES = {"material_delay", "labour", "weather", "equipment", "safety", "design", "quality", "other"}
SEVERITIES = {"low", "medium", "high"}


def parse(document: Any) -> TextModel:
    if not isinstance(document, dict) or document.get("format") != MODEL_FORMAT:
        raise TextModelError("Not a SiteSense text classifier.")
    models = document.get("models")
    if not isinstance(models, dict) or set(models) != {"category", "severity"}:
        raise TextModelError("The model must have a category and a severity classifier.")
    golden = document.get("golden", [])
    return TextModel(
        version=str(document.get("version", "")),
        category=_classifier(models["category"], CATEGORIES),
        severity=_classifier(models["severity"], SEVERITIES),
        metrics=dict(document.get("metrics", {})),
        golden=tuple(golden) if isinstance(golden, list) else (),
    )


def load(path: Path) -> TextModel:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TextModelError(f"Cannot read the text classifier at {path.name}: {exc}") from exc
    return parse(document)


@cache
def current() -> TextModel:
    """The classifier shipped with this build (loaded once per process)."""
    return load(MODELS_DIR / f"report-issues-v{CURRENT_VERSION}.json")
