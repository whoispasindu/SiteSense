"""Text handling for report issue tagging: split a report's problems into sentences, redact names.

Pure functions (no database). People's names are replaced with ``[PERSON]`` before a sentence is
classified or stored, so no name reaches a model input, an issue row, a log or (later) any outside
service. Three kinds of names are caught:

- the names of people the app knows on the project's site (their full names and each part of
  three letters or more), passed in by the caller;
- a capitalised word after a title or a site role ("Mr Perera", "foreman Sunil", "baas Nimal");
- common Sri Lankan given names and surnames in any case, with or without a title ("sunil absent"),
  from ``names_lk.txt``. That list holds only names that are not also everyday words.

A rare name that is in none of these still gets through; the model card says so. Company names are
left alone, except a listed name inside one ("Gamage Hardware" becomes "[PERSON] Hardware"): when
unsure, a word is removed rather than kept.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

PERSON = "[PERSON]"
MAX_SENTENCES = 20
MAX_SENTENCE_CHARS = 300

# "Problems: none" and similar mean there is nothing to tag.
_NOTHING = re.compile(
    r"^\s*(none|nil|no(ne)?\s+(issues?|problems?)(\s+today)?|n/?a|nothing|-+|ok|all good)\W*$", re.I
)
# Split on line breaks, sentence ends and semicolons, but not inside numbers such as "2.5".
_SPLIT = re.compile(r"(?:\r?\n)+|(?<!\d)[.!?]+|[.!?]+(?!\d)|;")
_TITLES = (
    r"mr|mrs|ms|miss|dr|eng|engineer|foreman|baas|bass|supervisor|site\s+agent|operator|driver|"
    r"mason|carpenter|helper|labourer|electrician|plumber|welder|storekeeper|security|mudalali|mahattaya"
)
# The title in any case ("Mr", "MR", "foreman"), then a capitalised name of one or two words.
_TITLED_NAME = re.compile(rf"\b((?i:{_TITLES}))\.?\s+([A-Z][a-z]{{2,}}(?:\s+[A-Z][a-z]{{2,}})?)")


def sentences(problems: str | None) -> list[str]:
    """The sentences worth tagging, in order: trimmed, de-duplicated, at most 20 of 300 characters."""
    if not problems or _NOTHING.match(problems):
        return []
    out: list[str] = []
    for part in _SPLIT.split(problems):
        text = re.sub(r"\s+", " ", part).strip(" -,*•")
        if len(re.sub(r"\W", "", text)) < 3 or _NOTHING.match(text):
            continue
        text = text[:MAX_SENTENCE_CHARS]
        if text.lower() not in (s.lower() for s in out):
            out.append(text)
        if len(out) == MAX_SENTENCES:
            break
    return out


# Parts of a name that are also everyday or site words are not redacted on their own (the demo users
# are called things like "Kasun Site Engineer"; real names such as "Mark" or "Rose" are also words).
_COMMON = {
    "site",
    "engineer",
    "project",
    "manager",
    "quantity",
    "surveyor",
    "procurement",
    "officer",
    "admin",
    "client",
    "company",
    "the",
    "and",
    "mark",
    "will",
    "rose",
    "grace",
    "may",
    "june",
    "bill",
    "rich",
    "sand",
    "stone",
    "hill",
    "wood",
    "mason",
    "steel",
    "king",
    "lucky",
    "sunny",
    "rain",
}


def _known_names(full_names: Iterable[str]) -> list[str]:
    names = set()
    for full in full_names:
        full = full.strip()
        if not full:
            continue
        names.add(full)
        names.update(
            part
            for part in re.split(r"[\s.()]+", full)
            if len(part) >= 3 and part[0].isalpha() and part.lower() not in _COMMON
        )
    # Longest first, so "Kasun Perera" is replaced before "Kasun".
    return sorted(names, key=len, reverse=True)


def _load_common_names(path: Path) -> re.Pattern[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        if not re.fullmatch(r"[a-z]{3,}", name) or name in _COMMON:
            raise ValueError(f"{path.name}: {name!r} must be a lower-case name of 3+ letters, not a word.")
        names.add(name)
    alternatives = "|".join(sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<![\w\[])(?:{alternatives})(?![\w\]])", re.I)


_COMMON_NAME = _load_common_names(Path(__file__).with_name("names_lk.txt"))
_ADJACENT = re.compile(rf"{re.escape(PERSON)}(?:\s+{re.escape(PERSON)})+")


def redact(text: str, people: Iterable[str] = ()) -> str:
    """Replace people's names with [PERSON]; a full name becomes a single [PERSON]."""
    for name in _known_names(people):
        text = re.sub(rf"(?<![\w\[]){re.escape(name)}(?![\w\]])", PERSON, text, flags=re.I)
    text = _TITLED_NAME.sub(lambda m: f"{m.group(1)} {PERSON}", text)
    text = _COMMON_NAME.sub(PERSON, text)
    return _ADJACENT.sub(PERSON, text)
