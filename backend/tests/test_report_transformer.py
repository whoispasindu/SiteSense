"""The DistilBERT category model (ONNX): parity with training, integrity checks, and the fallback."""

import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.ai.nlp import model as text_model
from app.ai.nlp import transformer
from app.ai.nlp.tagger import tag_problems

# CI fetches the model files first (scripts/fetch_models.py) and sets this, so the tests cannot be
# skipped there by accident. Locally they are skipped only if the files were never fetched.
REQUIRED = os.environ.get("SITESENSE_REQUIRE_MODELS") == "1"


@pytest.fixture(autouse=True)
def fresh_cache() -> Iterator[None]:
    transformer.current.cache_clear()
    yield
    transformer.current.cache_clear()


@pytest.fixture
def shipped() -> transformer.CategoryModel:
    try:
        return transformer.load()
    except transformer.TransformerError as exc:
        if REQUIRED:
            raise
        pytest.skip(f"model files not fetched ({exc}); run scripts/fetch_models.py")


def test_the_onnx_model_reproduces_its_training_predictions(shipped: transformer.CategoryModel) -> None:
    assert shipped.version == transformer.CURRENT_VERSION
    assert len(shipped.golden) >= 20
    for row in shipped.golden:
        [probabilities] = shipped.probabilities([row["text"]])
        for label, expected in zip(shipped.labels, row["category"], strict=True):
            assert probabilities[label] == pytest.approx(expected, abs=1e-4)


def test_tc06_with_the_shipped_models(shipped: transformer.CategoryModel) -> None:
    [tag] = tag_problems("cement not delivered again", category_model=shipped)

    assert (tag.category, tag.severity, tag.model_version) == ("material_delay", "high", "1.1.0")


def test_the_manifest_records_the_evidence_for_adopting_the_model() -> None:
    evidence = transformer.manifest()["evidence"]

    assert evidence["distilbert_onnx_fp32"] - evidence["baseline_category_macro_f1"] >= 0.05
    assert evidence["gain_fp32_vs_baseline_bootstrap"]["low"] > 0  # the gain is clear of zero


def _with_manifest(monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]) -> None:
    document = transformer.manifest()
    document["files"]["model"].update(changes)
    monkeypatch.setattr(transformer, "manifest", lambda version=transformer.CURRENT_VERSION: document)


def test_a_file_of_the_wrong_size_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    name = transformer.manifest()["files"]["model"]["name"]
    (tmp_path / name).write_bytes(b"not a model")

    with pytest.raises(transformer.TransformerError, match="wrong size"):
        transformer.load(tmp_path)


def test_a_tampered_file_is_refused_before_it_is_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = b"\x08\x07" + b"x" * 100  # never reaches onnxruntime
    _with_manifest(monkeypatch, {"name": "model.onnx", "bytes": len(fake)})
    (tmp_path / "model.onnx").write_bytes(fake)

    with pytest.raises(transformer.TransformerError, match="SHA-256"):
        transformer.load(tmp_path)


def test_missing_files_fall_back_to_the_tfidf_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transformer, "FILES_DIR", tmp_path)  # nothing fetched here

    assert transformer.current() is None
    [tag] = tag_problems("Mixer broke down")
    assert tag.model_version == text_model.CURRENT_VERSION
    assert tag.category == "equipment"


@pytest.mark.parametrize("name", ["../secrets.onnx", "sub/dir.onnx", ".hidden", "a\\b.onnx", ""])
def test_manifest_file_names_must_be_plain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    document = json.loads(
        (
            transformer.MODELS_DIR / f"report-issues-category-v{transformer.CURRENT_VERSION}.manifest.json"
        ).read_text()
    )
    document["files"]["model"]["name"] = name
    path = tmp_path / f"report-issues-category-v{transformer.CURRENT_VERSION}.manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(transformer, "MODELS_DIR", tmp_path)

    with pytest.raises(transformer.TransformerError, match="plain names"):
        transformer.manifest()


def test_an_unreadable_manifest_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transformer, "MODELS_DIR", tmp_path)

    with pytest.raises(transformer.TransformerError, match="Cannot read"):
        transformer.manifest()
    (tmp_path / f"report-issues-category-v{transformer.CURRENT_VERSION}.manifest.json").write_text(
        '{"format": "x"}'
    )
    with pytest.raises(transformer.TransformerError, match="Not a SiteSense"):
        transformer.manifest()


def test_scoring_does_not_depend_on_other_sentences(shipped: transformer.CategoryModel) -> None:
    """Full precision has no batch effect: a sentence scores the same alone or with others."""
    alone = shipped.probabilities(["crane down"])[0]
    together = shipped.probabilities(["crane down", "a much longer sentence about cement deliveries"])[0]

    assert alone == pytest.approx(together, abs=1e-5)


def test_onnxruntime_telemetry_is_off_before_onnxruntime_is_imported() -> None:
    """onnxruntime's Linux build calls Microsoft's telemetry service unless told not to at import time.

    In a fresh interpreter without the variable, load the code that tags reports and record the
    setting at the moment onnxruntime is first imported, whichever module imports it first.
    """
    probe = textwrap.dedent(
        """
        import os, sys
        seen = []
        class Watch:
            def find_spec(self, name, path=None, target=None):
                if name == "onnxruntime" and not seen:
                    seen.append(os.environ.get("ORT_DISABLE_TELEMETRY"))
        sys.meta_path.insert(0, Watch())
        import app.api.router, app.services.issue_service, app.cli
        print(seen)
        """
    )
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", probe],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "['1']"
