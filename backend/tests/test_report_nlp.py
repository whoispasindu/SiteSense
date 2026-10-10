"""Report issue tagging without a database: splitting, redaction, the classifier, the guide's rules."""

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.ai.nlp import model as text_model
from app.ai.nlp import rules
from app.ai.nlp.tagger import LOW_CONFIDENCE, tag_problems, tag_sentence
from app.ai.nlp.text import PERSON, redact, sentences

# --- Splitting ----------------------------------------------------------------------------------------


def test_problems_are_split_into_sentences() -> None:
    text = (
        "Cement not delivered again. Crane down; foreman says 2.5 days to fix!\n"
        "- rain after 3pm\n\nCrane down"
    )

    assert sentences(text) == [
        "Cement not delivered again",
        "Crane down",
        "foreman says 2.5 days to fix",
        "rain after 3pm",
    ]


@pytest.mark.parametrize("text", [None, "", "None", "nil", "No issues today.", "N/A", "-", "all good", "  "])
def test_nothing_to_tag(text: str | None) -> None:
    assert sentences(text) == []


def test_a_sentence_ending_in_a_number_is_split() -> None:
    assert sentences("Blocks short on level 3. Rain from 2.30 pm") == [
        "Blocks short on level 3",
        "Rain from 2.30 pm",
    ]


def test_sentences_are_capped() -> None:
    many = ". ".join(f"problem number {i}" for i in range(40))

    assert len(sentences(many)) == 20
    assert all(len(s) <= 300 for s in sentences("x" * 1000))


# --- Names --------------------------------------------------------------------------------------------


def test_names_of_people_on_site_are_redacted() -> None:
    text = "Kasun did not come; told kasun perera again. Site engineer informed."

    redacted = redact(text, ["Kasun Perera", "Ruwan Site Engineer"])

    assert redacted == f"{PERSON} did not come; told {PERSON} again. Site engineer informed."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mr Perera says the lorry broke down", f"Mr {PERSON} says the lorry broke down"),
        ("MR Silva phoned", f"MR {PERSON} phoned"),
        ("foreman Sunil Fernando absent", f"foreman {PERSON} absent"),
        ("baas Nimal went home", f"baas {PERSON} went home"),
        ("the Mason gang idle", "the Mason gang idle"),  # a trade, not a name
        ("Kelani Building Supplies late again", "Kelani Building Supplies late again"),  # a company
    ],
)
def test_titled_names_are_redacted(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_everyday_words_in_a_name_are_not_redacted() -> None:
    assert redact("site engineer and project manager on leave", ["Kasun Site Engineer", "Rose Mark"]) == (
        "site engineer and project manager on leave"
    )


# --- The shipped classifier ------------------------------------------------------------------------------


def test_shipped_classifier_reproduces_scikit_learn() -> None:
    """Golden probabilities from training; coefficients are stored to 6 decimals."""
    shipped = text_model.current()

    assert len(shipped.golden) >= 20
    for row in shipped.golden:
        for target in ("category", "severity"):
            clf = getattr(shipped, target)
            probabilities = clf.probabilities(row["text"])
            for label, expected in zip(sorted(clf.classes), row[target], strict=True):
                assert probabilities[label] == pytest.approx(expected, abs=1e-5)


def test_probabilities_sum_to_one() -> None:
    shipped = text_model.current()
    for text in ("rebar late", "", "!!!", "x" * 300):
        assert sum(shipped.category.probabilities(text).values()) == pytest.approx(1.0)


def _document() -> dict[str, Any]:
    vec = {"analyzer": "word", "ngram_range": [1, 1], "terms": ["cement", "crane"], "idf": [1.0, 1.0]}
    cats = sorted(text_model.CATEGORIES)
    sevs = sorted(text_model.SEVERITIES)
    return {
        "format": "sitesense-textclf-v1",
        "version": "0.0.1",
        "models": {
            "category": {
                "vectorizers": [vec],
                "classes": cats,
                "coef": [[0.0, 0.0] for _ in cats],
                "intercept": [0.0] * len(cats),
            },
            "severity": {
                "vectorizers": [vec],
                "classes": sevs,
                "coef": [[0.0, 0.0] for _ in sevs],
                "intercept": [0.0] * len(sevs),
            },
        },
    }


def test_a_tiny_document_scores_as_expected() -> None:
    doc = _document()
    cats = doc["models"]["category"]["classes"]
    doc["models"]["category"]["coef"][cats.index("equipment")] = [0.0, 5.0]

    model = text_model.parse(doc)
    probabilities = model.category.probabilities("Crane broke down")

    assert max(probabilities, key=probabilities.__getitem__) == "equipment"
    assert probabilities["equipment"] == pytest.approx(math.exp(5) / (math.exp(5) + 7))


def _broken(change: str) -> dict[str, Any]:
    doc = _document()
    cat = doc["models"]["category"]
    vec = cat["vectorizers"][0]
    if change == "format":
        doc["format"] = "joblib"
    elif change == "missing target":
        del doc["models"]["severity"]
    elif change == "analyzer":
        vec["analyzer"] = "regex"
    elif change == "ngram range":
        vec["ngram_range"] = [3, 1]
    elif change == "duplicate terms":
        vec["terms"] = ["cement", "cement"]
    elif change == "negative idf":
        vec["idf"] = [1.0, -1.0]
    elif change == "idf length":
        vec["idf"] = [1.0]
    elif change == "wrong classes":
        cat["classes"] = [*cat["classes"][:-1], "fire"]
    elif change == "coef width":
        cat["coef"][0] = [0.0]
    elif change == "infinite coef":
        cat["coef"][0] = [math.inf, 0.0]
    elif change == "text coef":
        cat["coef"][0] = ["1", 0.0]
    elif change == "intercepts":
        cat["intercept"] = [0.0]
    elif change == "no vectorizer":
        cat["vectorizers"] = []
    return doc


@pytest.mark.parametrize(
    "change",
    ["format", "missing target", "analyzer", "ngram range", "duplicate terms", "negative idf", "idf length",
     "wrong classes", "coef width", "infinite coef", "text coef", "intercepts", "no vectorizer"],
)  # fmt: skip
def test_malformed_classifiers_are_refused(change: str) -> None:
    with pytest.raises(text_model.TextModelError):
        text_model.parse(_broken(change))


def test_unreadable_classifier_files_are_refused(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")

    with pytest.raises(text_model.TextModelError, match="Cannot read"):
        text_model.load(tmp_path / "bad.json")
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_document()), encoding="utf-8")
    assert text_model.load(good).version == "0.0.1"


def test_char_ngrams_match_scikit_learn_padding() -> None:
    vec = text_model.Vectorizer("char_wb", 2, 3, {}, ())

    assert vec.grams("ab  c") == [" a", "ab", "b ", " ab", "ab ", " c", "c ", " c "]


# --- The labelling guide's severity rules ---------------------------------------------------------------


def constant(level: str):  # type: ignore[no-untyped-def]
    return lambda _text: level


@pytest.mark.parametrize(
    ("text", "model_says", "expected"),
    [
        ("cement late", "medium", "medium"),
        ("cement late again", "medium", "high"),  # repetition: one step up
        ("blocks slightly late again", "low", "medium"),
        ("rain for the third day running", "medium", "high"),
        ("a helper fell from the ladder", "low", "high"),  # any injury is high
        ("work stopped at noon", "medium", "high"),
        ("pour cancelled", "low", "high"),
        ("crane down", "high", "high"),
    ],
)
def test_guide_rules(text: str, model_says: str, expected: str) -> None:
    assert rules.severity(text, constant(model_says)) == expected


def test_repetition_is_judged_without_the_repeat_words() -> None:
    seen: list[str] = []

    def model(text: str) -> str:
        seen.append(text)
        return "low"

    assert rules.severity("Paint late again", model) == "medium"
    assert seen == ["Paint late"]


# --- Tagging --------------------------------------------------------------------------------------------


def test_tc06_cement_not_delivered_again_is_a_high_material_delay() -> None:
    """TC-06 (the risk re-score is checked in test_issues_api.py)."""
    [tag] = tag_problems("cement not delivered again")

    assert (tag.category, tag.severity) == ("material_delay", "high")
    assert tag.low_confidence is False


def test_names_never_reach_the_classifier() -> None:
    [tag] = tag_problems("Kasun Perera did not report for work", ["Kasun Perera"])

    assert tag.snippet == f"{PERSON} did not report for work"


def test_unclear_sentences_are_marked_low_confidence() -> None:
    tag = tag_sentence("the thing with the stuff", text_model.current())

    assert tag.confidence < LOW_CONFIDENCE
    assert tag.low_confidence is True


def test_a_report_gives_one_tag_per_sentence_in_order() -> None:
    tags = tag_problems("Heavy rain from 10am, pour postponed. Mixer broke down. Two masons absent.")

    assert [t.category for t in tags] == ["weather", "equipment", "labour"]


def test_the_shipped_file_is_validated_before_use(monkeypatch: pytest.MonkeyPatch) -> None:
    shipped = copy.deepcopy(
        json.loads((text_model.MODELS_DIR / f"report-issues-v{text_model.CURRENT_VERSION}.json").read_text())
    )
    shipped["models"]["category"]["coef"][0][0] = "not a number"

    with pytest.raises(text_model.TextModelError):
        text_model.parse(shipped)
