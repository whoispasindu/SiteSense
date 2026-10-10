"""Tag the problems in a daily report: split into sentences, redact names, classify, apply the rules.

For each sentence the classifier gives a category and a severity with probabilities. The labelling
guide's severity rules (``rules.py``) are applied around the severity model. A tag whose category
probability is below ``LOW_CONFIDENCE`` is marked low-confidence: the screen highlights it and the
author must look at it before confirming. Nothing here is stored; ``issue_service`` does that.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.ai.nlp import model as text_model
from app.ai.nlp import rules, transformer
from app.ai.nlp.text import redact, sentences

# Below this category probability a tag is shown as "check this". Chosen on the validation set so
# that most correct tags clear it and most wrong ones do not (see the model card).
LOW_CONFIDENCE = 0.6


@dataclass(frozen=True, slots=True)
class Tag:
    snippet: str  # the sentence, names redacted
    category: str
    severity: str
    confidence: float  # the category probability
    low_confidence: bool
    model_version: str  # the classifier version that produced the tag


def _tag(snippet: str, categories: dict[str, float], model: text_model.TextModel, version: str) -> Tag:
    category = max(categories, key=categories.__getitem__)

    def predict_severity(text: str) -> str:
        probabilities = model.severity.probabilities(text)
        return max(probabilities, key=probabilities.__getitem__)

    confidence = categories[category]
    return Tag(
        snippet=snippet,
        category=category,
        severity=rules.severity(snippet, predict_severity),
        confidence=round(confidence, 3),
        low_confidence=confidence < LOW_CONFIDENCE,
        model_version=version,
    )


def tag_sentence(snippet: str, model: text_model.TextModel) -> Tag:
    """One sentence with the TF-IDF models only (the fallback, and for tests)."""
    return _tag(snippet, model.category.probabilities(snippet), model, model.version)


_AUTO = object()


def tag_problems(
    problems: str | None,
    people: Iterable[str] = (),
    model: text_model.TextModel | None = None,
    category_model: Any = _AUTO,
) -> list[Tag]:
    """Tags for each sentence of a report's problems, in order. Names are redacted before anything else.

    The category comes from the DistilBERT model when its files are present and verified (version
    1.1.0), otherwise from the TF-IDF model (1.0.0). Severity always comes from the TF-IDF severity
    model with the labelling guide's rules: DistilBERT did not beat it there (see the model card).
    """
    model = model or text_model.current()
    category: transformer.CategoryModel | None = (
        transformer.current() if category_model is _AUTO else category_model
    )
    names = list(people)
    snippets = [redact(sentence, names) for sentence in sentences(problems)]
    if category is not None:
        probabilities = category.probabilities(snippets)
        version = category.version
    else:
        probabilities = [model.category.probabilities(s) for s in snippets]
        version = model.version
    return [_tag(s, p, model, version) for s, p in zip(snippets, probabilities, strict=True)]
