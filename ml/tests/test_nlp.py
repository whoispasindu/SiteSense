"""Report issue data and rules: the test set stays separate, the generator is reproducible."""

import csv
import re
from pathlib import Path

import pytest

from nlp import generate, rules
from nlp.train_baseline import CATEGORIES, SEVERITIES

DATA = Path(__file__).parents[1] / "nlp" / "data"


def rows(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def normal(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def test_the_hand_written_test_set_never_appears_in_training_data() -> None:
    test = {normal(r["text"]) for r in rows("test_handwritten.csv")}
    training = {normal(r["text"]) for name in ("train.csv", "val.csv") for r in rows(name)}

    assert len(test) >= 190
    assert not test & training


def test_labels_are_from_the_guide() -> None:
    for name in ("train.csv", "val.csv", "test_handwritten.csv"):
        for row in rows(name):
            assert row["category"] in CATEGORIES, row
            assert row["severity"] in SEVERITIES, row


def test_every_class_is_in_the_test_set() -> None:
    test = rows("test_handwritten.csv")

    assert {r["category"] for r in test} == set(CATEGORIES)
    assert {r["severity"] for r in test} == set(SEVERITIES)
    assert min(sum(r["category"] == c for r in test) for c in CATEGORIES) >= 20


def test_validation_holds_out_whole_templates() -> None:
    """Templates in validation never appear in training, so tuning rewards new wording."""
    train, val = rows("train.csv"), rows("val.csv")

    assert len(train) > len(val) > 200
    assert not {normal(r["text"]) for r in train} & {normal(r["text"]) for r in val}


def test_the_generator_is_reproducible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "data"
    out.mkdir()
    (out / "test_handwritten.csv").write_text(
        (DATA / "test_handwritten.csv").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(generate, "DATA", out)

    generate.main()

    assert (out / "train.csv").read_text(encoding="utf-8") == (DATA / "train.csv").read_text(encoding="utf-8")
    assert (out / "val.csv").read_text(encoding="utf-8") == (DATA / "val.csv").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("text", "model_says", "expected"),
    [
        ("cement late", "medium", "medium"),
        ("cement late again", "medium", "high"),
        ("blocks slightly late again", "low", "medium"),
        ("rain for the third day running", "medium", "high"),
        ("a helper fell from the ladder", "low", "high"),
        ("work stopped at noon", "medium", "high"),
        ("pour cancelled", "low", "high"),
        ("crane down", "high", "high"),
    ],
)
def test_guide_rules_match_the_backend_cases(text: str, model_says: str, expected: str) -> None:
    """Same cases as backend/tests/test_report_nlp.py::test_guide_rules."""
    assert rules.severity(text, lambda _t: model_says) == expected
