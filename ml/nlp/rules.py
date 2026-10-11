"""Severity rules from the labelling guide, applied around a model's prediction.

Mirrored in backend/app/ai/nlp/rules.py (tests in both cover the same cases). The rules come from
LABELLING.md, not from the test set:

- any injury, a collapse, or work stopped or lost is high;
- repetition ("again", "third day running") raises severity by one step. To apply it the way the
  guide means, the model judges the sentence *without* the repetition words, and the result is
  raised one step, so a model that has partly learnt "again" does not count it twice.
"""

from __future__ import annotations

import re
from collections.abc import Callable

LEVELS = ("low", "medium", "high")
HIGH = re.compile(
    r"\b(injur\w*|hurt|hospital\w*|fell|fall(en)? from|bleed\w*|fractur\w*|electric shock|faint\w*|"
    r"unconscious|collaps\w*|work stopped|stopped work|stop work|stop-work|halted|standstill|"
    r"whole day lost|lost the (whole )?day|cancel+ed|nothing (was |could be )?done)\b",
    re.I,
)
REPEAT = re.compile(
    r"\b(again|agn|once more|yet again|(2nd|second|3rd|third|4th|fourth) (time|day)( this week| running)?|"
    r"same as yesterday|as usual|days? running|every day)\b",
    re.I,
)


def severity(text: str, predict: Callable[[str], str]) -> str:
    """Severity for a sentence: the guide's rules around ``predict`` (a model's severity for a text)."""
    if HIGH.search(text):
        return "high"
    if REPEAT.search(text):
        stripped = re.sub(r"\s+", " ", REPEAT.sub(" ", text)).strip(" ,.-;") or text
        return LEVELS[min(LEVELS.index(predict(stripped)) + 1, 2)]
    return predict(text)
