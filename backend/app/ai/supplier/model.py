"""The supplier on-time model (BR-12, Phase 10): how likely a supplier's next order arrives on time.

Trained in ``ml/train_supplier.py`` on simulated delivery histories, and exported as plain JSON (no
pickles). Two kinds exist; the training code ships the logistic model only if it is clearly better:

- ``smoothed``: the supplier's on-time share, pulled towards the company's as if by a few average
  deliveries (the chance is that share);
- ``logistic``: logistic regression on that share's log-odds, how many deliveries it rests on, the
  lead time, a short-lead flag and the wet season at the site.

Whichever ships, every estimate says how many deliveries it rests on, and a supplier with fewer
than ``low_data_deliveries`` is marked as low data, so a BR-12 suggestion about it reads as tentative.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, TypeGuard

MODELS_DIR = Path(__file__).parent / "models"
MODEL_FORMAT = "sitesense-supplier-v1"
CURRENT_VERSION = "1.0.0"
INPUTS = ("supplier_logit", "log_deliveries", "lead_time_days", "wet_share", "short_lead")
DERIVED = "supplier_logit_x_log_deliveries"


class SupplierModelError(ValueError):
    """The model file is missing or not a valid supplier model."""


def _number(value: Any) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def smoothed(on_time: float, count: float, prior: float, strength: float) -> float:
    return (on_time + strength * prior) / (count + strength)


@dataclass(frozen=True, slots=True)
class SupplierModel:
    version: str
    kind: str  # "smoothed" or "logistic"
    features: tuple[str, ...]
    intercept: float
    coef: tuple[float, ...]
    prior_strength: float
    default_rate: float
    company_prior_strength: float
    short_lead_days: float
    low_data_deliveries: int
    golden: tuple[dict[str, Any], ...]

    def inputs(
        self,
        *,
        supplier_on_time: float,
        supplier_count: float,
        company_on_time: float,
        company_count: float,
        lead_time_days: float,
        wet_share: float,
    ) -> dict[str, float]:
        """The model's inputs, exactly as the simulator computes them (ml/data_generator/deliveries.py)."""
        company = smoothed(company_on_time, company_count, self.default_rate, self.company_prior_strength)
        rate = smoothed(supplier_on_time, supplier_count, company, self.prior_strength)
        lead = min(max(lead_time_days, 0.0), 120.0)
        return {
            "supplier_logit": logit(rate),
            "log_deliveries": math.log1p(supplier_count),
            "lead_time_days": lead,
            "wet_share": wet_share,
            "short_lead": max(0.0, self.short_lead_days - lead) / self.short_lead_days,
        }

    def chance(self, inputs: dict[str, float]) -> float:
        """The chance (0 to 1) that the next order arrives on time."""
        if not all(_number(inputs.get(name)) for name in INPUTS):
            raise SupplierModelError("Every input must be a finite number.")
        if self.kind == "smoothed":
            return sigmoid(inputs["supplier_logit"])
        values = {**inputs, DERIVED: inputs["supplier_logit"] * inputs["log_deliveries"]}
        return sigmoid(
            self.intercept + sum(c * values[f] for c, f in zip(self.coef, self.features, strict=True))
        )


def parse(document: Any) -> SupplierModel:
    if not isinstance(document, dict) or document.get("format") != MODEL_FORMAT:
        raise SupplierModelError("Not a SiteSense supplier model.")
    kind = document.get("kind")
    if kind not in ("smoothed", "logistic"):
        raise SupplierModelError("Unknown model kind.")
    features = document.get("features")
    if not isinstance(features, list) or set(features) - {*INPUTS, DERIVED}:
        raise SupplierModelError("The model uses inputs this app does not compute.")
    coef, intercept = document.get("coef"), document.get("intercept")
    if not (isinstance(coef, list) and len(coef) == len(features) and all(_number(c) for c in coef)):
        raise SupplierModelError("One finite coefficient per input is needed.")
    if not _number(intercept):
        raise SupplierModelError("A finite intercept is needed.")
    constants = document.get("constants")
    names = (
        "prior_strength",
        "default_rate",
        "company_prior_strength",
        "short_lead_days",
        "low_data_deliveries",
    )
    if not isinstance(constants, dict) or not all(
        _number(constants.get(n)) and constants[n] > 0 for n in names
    ):
        raise SupplierModelError("The model's constants must be positive numbers.")
    if not 0 < constants["default_rate"] < 1:
        raise SupplierModelError("The default on-time rate must be between 0 and 1.")
    golden = document.get("golden", [])
    return SupplierModel(
        version=str(document.get("version", "")),
        kind=str(kind),
        features=tuple(str(f) for f in features),
        intercept=float(intercept),
        coef=tuple(float(c) for c in coef),
        prior_strength=float(constants["prior_strength"]),
        default_rate=float(constants["default_rate"]),
        company_prior_strength=float(constants["company_prior_strength"]),
        short_lead_days=float(constants["short_lead_days"]),
        low_data_deliveries=int(constants["low_data_deliveries"]),
        golden=tuple(golden) if isinstance(golden, list) else (),
    )


def load(path: Path) -> SupplierModel:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SupplierModelError(f"Cannot read the supplier model at {path.name}: {exc}") from exc
    return parse(document)


@cache
def current() -> SupplierModel:
    return load(MODELS_DIR / f"supplier-v{CURRENT_VERSION}.json")
