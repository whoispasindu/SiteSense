"""The DistilBERT category model (ONNX), with integrity checks and a fallback.

The model and its tokenizer are too large for the repository (266 MB), so they are attached to a
GitHub Release and fetched into ``models/report-issues-category/`` by ``scripts/fetch_models.py``.
The committed manifest pins each file's SHA-256 and size. Files are checked *before* onnxruntime
parses them, so a tampered or truncated file is never loaded.

If the files are missing or do not match, ``current()`` returns None and the tagger uses the TF-IDF
category model instead (logged once). Each stored issue records the version that tagged it.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

# onnxruntime's Linux build sends usage telemetry to Microsoft (mobile.events.data.microsoft.com)
# unless this is set before it is imported. The server must not call out to third parties.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from app.core.logging import get_logger

log = get_logger(__name__)

MODELS_DIR = Path(__file__).parent / "models"
FILES_DIR = MODELS_DIR / "report-issues-category"
CURRENT_VERSION = "1.1.0"
MANIFEST_FORMAT = "sitesense-onnx-textclf-v1"
MAX_BYTES = 300 * 1024 * 1024


class TransformerError(ValueError):
    """The manifest or the model files are not valid."""


@dataclass(frozen=True)
class CategoryModel:
    version: str
    labels: tuple[str, ...]
    session: ort.InferenceSession
    tokenizer: Tokenizer
    golden: tuple[dict[str, Any], ...]

    def probabilities(self, texts: list[str]) -> list[dict[str, float]]:
        if not texts:
            return []
        encodings = self.tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        logits = self.session.run(["category_logits"], {"input_ids": ids, "attention_mask": mask})[0]
        out = []
        for row in logits:
            top = float(max(row))
            exps = [math.exp(float(v) - top) for v in row]
            total = sum(exps)
            out.append({label: e / total for label, e in zip(self.labels, exps, strict=True)})
        return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest(version: str = CURRENT_VERSION) -> dict[str, Any]:
    path = MODELS_DIR / f"report-issues-category-v{version}.manifest.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransformerError(f"Cannot read the manifest {path.name}: {exc}") from exc
    if not isinstance(document, dict) or document.get("format") != MANIFEST_FORMAT:
        raise TransformerError("Not a SiteSense ONNX classifier manifest.")
    labels = document.get("labels")
    files = document.get("files")
    if not (isinstance(labels, list) and labels and all(isinstance(x, str) for x in labels)):
        raise TransformerError("The manifest must list the labels.")
    if not (isinstance(files, dict) and {"model", "tokenizer"} <= set(files)):
        raise TransformerError("The manifest must pin the model and tokenizer files.")
    for entry in files.values():
        name = entry.get("name", "") if isinstance(entry, dict) else ""
        if not (
            isinstance(name, str)
            and name
            and "/" not in name
            and "\\" not in name
            and not name.startswith(".")
        ):
            raise TransformerError("File names must be plain names.")
    return document


def _checked(entry: dict[str, Any], directory: Path) -> Path:
    path = directory / str(entry["name"])
    if not path.is_file():
        raise TransformerError(f"{entry['name']} is missing; run scripts/fetch_models.py.")
    size = path.stat().st_size
    if size != entry.get("bytes") or size > MAX_BYTES:
        raise TransformerError(f"{entry['name']} has the wrong size.")
    if _sha256(path) != entry.get("sha256"):
        raise TransformerError(f"{entry['name']} does not match its SHA-256 in the manifest.")
    return path


def load(directory: Path | None = None, version: str = CURRENT_VERSION) -> CategoryModel:
    directory = directory or FILES_DIR
    document = manifest(version)
    model_path = _checked(document["files"]["model"], directory)
    tokenizer_path = _checked(document["files"]["tokenizer"], directory)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    length = int(document.get("max_length", 48))
    tokenizer.enable_truncation(length)
    tokenizer.enable_padding(length=length)
    return CategoryModel(
        version=str(document["version"]),
        labels=tuple(document["labels"]),
        session=session,
        tokenizer=tokenizer,
        golden=tuple(document.get("golden", [])),
    )


@cache
def current() -> CategoryModel | None:
    """The shipped category model, or None (with one warning) when its files are not available."""
    try:
        return load()
    except TransformerError as exc:
        log.warning("report_classifier_fallback", reason=str(exc), fallback="tfidf")
        return None
