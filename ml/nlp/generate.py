"""Synthetic training sentences for the report issue classifier (train and validation only).

    python -m nlp.generate          # writes nlp/data/train.csv and nlp/data/val.csv

Sentences are composed from parts: what is affected (an item), what happened to it (an event, by
severity), an optional consequence, and where or when. Severity follows LABELLING.md, including
"repetition raises severity by one step". Noise is added the way site notes are written: lower
case, dropped apostrophes, abbreviations, typos, terse forms and a few Sinhala words in English
letters.

Validation holds out whole event templates (about a fifth per category), so the settings chosen on
it are the ones that generalise to wording the model has not seen. The hand-written test set
(data/test_handwritten.csv) is never read for training; this script only checks that it does not
reproduce any test sentence.
"""

from __future__ import annotations

import csv
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
SEED = 7
PER_CATEGORY = 190
VAL_TEMPLATE_SHARE = 0.2
LEVELS = ["low", "medium", "high"]

PLACES = [
    "on level 2",
    "at grid D",
    "in the basement",
    "on the roof",
    "near the main gate",
    "at block B",
    "on the east side",
    "in the stair core",
    "at the podium",
    "on the 5th floor",
    "at the lift shaft",
    "along the boundary",
    "in the car park area",
    "on the north elevation",
]
TIMES = [
    "this morning",
    "after lunch",
    "since 8am",
    "today",
    "in the afternoon",
    "from 10 o'clock",
    "the whole day",
    "around noon",
    "before tea break",
    "late evening",
]
REPEAT = [
    "again",
    "once more",
    "for the second time",
    "same as yesterday",
    "third day running",
    "as usual",
    "yet again",
    "for the 3rd time this week",
]
CONSEQUENCE = {
    "high": [
        "work stopped",
        "the gang was idle",
        "we lost the whole day",
        "the pour had to be cancelled",
        "nothing could be done",
        "site at a standstill",
        "everyone sent home early",
        "big setback",
    ],
    "medium": [
        "work slowed down",
        "lost a couple of hours",
        "crew partly idle",
        "progress behind",
        "had to shift the crew to other work",
        "need to catch up tomorrow",
        "programme slipping",
    ],
    "low": [
        "no real impact",
        "managed with what we had",
        "sorted out quickly",
        "will monitor",
        "not affecting progress",
        "fine for now",
        "just noting it",
    ],
}

# Each category: items, and event templates per severity. {i} is the item.
BANK: dict[str, dict[str, list[str]]] = {
    "material_delay": {
        "items": [
            "cement",
            "sand",
            "rebar",
            "steel",
            "blocks",
            "bricks",
            "floor tiles",
            "metal",
            "ready mix",
            "timber",
            "ply sheets",
            "PVC pipes",
            "conduits",
            "roofing sheets",
            "emulsion paint",
            "door frames",
            "aluminium windows",
            "binding wire",
            "aggregate",
            "wall putty",
            "cables",
            "sanitaryware",
            "reinforcement mesh",
            "formwork props",
            "quarry dust",
            "granite slabs",
        ],
        "high": [
            "{i} never arrived",
            "no {i} on site at all",
            "{i} order cancelled by the supplier",
            "the {i} lorry did not come",
            "{i} supplier let us down",
            "ran out of {i} completely",
            "{i} not supplied even after 3 reminders",
            "nothing from the {i} supplier",
        ],
        "medium": [
            "{i} came late",
            "still waiting for {i}",
            "{i} short supplied",
            "only part of the {i} came",
            "{i} delivery postponed to tomorrow",
            "{i} running low",
            "{i} held up at the depot",
            "{i} quantity less than ordered",
        ],
        "low": [
            "{i} slightly late",
            "{i} came an hour late",
            "small shortage of {i}",
            "{i} delivery a bit behind",
            "{i} expected tomorrow, have enough for now",
            "{i} came after lunch instead of morning",
        ],
    },
    "labour": {
        "items": [
            "masons",
            "carpenters",
            "steel fixers",
            "helpers",
            "labourers",
            "painters",
            "tilers",
            "plumbers",
            "electricians",
            "welders",
            "the night crew",
            "the formwork gang",
            "the sub-contractor's men",
            "skilled workers",
            "the plaster gang",
            "operators",
            "the rebar gang",
            "casual workers",
        ],
        "high": [
            "{i} did not turn up",
            "{i} on strike",
            "{i} walked off the job",
            "none of the {i} came",
            "{i} refused to work",
            "{i} pulled out by the sub contractor",
            "all {i} absent",
        ],
        "medium": [
            "only half the {i} came",
            "short of {i}",
            "{i} came late and left early",
            "need more {i}",
            "{i} gang reduced",
            "few {i} reported",
            "{i} working slowly",
        ],
        "low": [
            "one of the {i} absent",
            "{i} a little late",
            "a couple of {i} on leave",
            "new {i} still learning",
            "{i} took a long lunch",
        ],
    },
    "weather": {
        "items": [
            "rain",
            "heavy rain",
            "a thunderstorm",
            "strong wind",
            "flooding",
            "extreme heat",
            "monsoon showers",
            "drizzle",
            "lightning",
            "a downpour",
            "wet weather",
            "storm",
        ],
        "high": [
            "{i} all day",
            "{i} flooded the site",
            "{i} made the excavation collapse",
            "{i} stopped all outdoor work",
            "{i} forced us to stop concreting",
            "lost the day to {i}",
        ],
        "medium": [
            "{i} slowed the work",
            "{i} delayed the start",
            "{i} interrupted the plastering",
            "{i} for a few hours",
            "{i} made the access road muddy",
            "work paused because of {i}",
        ],
        "low": [
            "a little {i}",
            "short spell of {i}",
            "{i} for a few minutes",
            "{i} forecast for later",
            "light {i} in the evening",
        ],
    },
    "equipment": {
        "items": [
            "crane",
            "tower crane",
            "mixer",
            "concrete pump",
            "hoist",
            "generator",
            "excavator",
            "compactor",
            "welding machine",
            "poker vibrator",
            "dumper",
            "bar cutter",
            "batching plant",
            "water pump",
            "backhoe",
            "scaffold winch",
            "roller",
            "boom lift",
            "drill",
        ],
        "high": [
            "{i} broke down",
            "{i} out of order",
            "{i} failed during the pour",
            "{i} still under repair",
            "{i} totally broken",
            "{i} burnt out",
            "{i} not working at all",
        ],
        "medium": [
            "{i} gave trouble",
            "{i} down for a few hours",
            "{i} needs repair",
            "{i} arrived late from hire",
            "{i} ran out of fuel",
            "{i} overheating",
            "{i} keeps stalling",
        ],
        "low": [
            "{i} needs servicing",
            "small fault on the {i}",
            "{i} making a noise",
            "{i} started late",
            "{i} oil change due",
            "{i} tyre pressure low",
        ],
    },
    "safety": {
        "items": [
            "a labourer",
            "a helper",
            "a mason",
            "a carpenter",
            "a steel fixer",
            "a worker",
            "the scaffolder",
            "a painter",
            "an electrician",
            "a welder",
        ],
        "high": [
            "{i} fell from height",
            "{i} was injured",
            "{i} taken to hospital",
            "{i} got an electric shock",
            "{i} working at height with no harness",
            "{i} hit by falling material",
            "scaffold collapsed near {i}",
            "{i} cut badly and bleeding",
            "edge protection missing at the slab edge",
            "lift shaft opening left unguarded",
            "deep trench with no shoring",
            "crane swinging loads over the workers",
        ],
        "medium": [
            "near miss with {i}",
            "{i} without a helmet",
            "{i} using an unsafe ladder",
            "{i} not wearing safety shoes",
            "{i} welding without goggles",
            "{i} standing under a suspended load",
            "no barricade where {i} was working",
            "PPE not worn by the gang",
            "safety net not put up yet",
            "damaged extension cords on the floor",
            "gas bottles kept near hot work",
            "no hand rails on the stairs",
        ],
        "low": [
            "first aid kit low",
            "safety signs faded",
            "reminded {i} about PPE",
            "housekeeping poor",
            "fire extinguisher due for refill",
            "toolbox talk missed",
            "PPE stock running low",
            "need more reflective vests",
        ],
    },
    "design": {
        "items": [
            "the beam",
            "the column",
            "the staircase",
            "the slab",
            "the lift core",
            "the facade",
            "the toilet layout",
            "the roof truss",
            "the ramp",
            "the water tank",
            "the boundary wall",
            "the lintel",
            "the parapet",
            "the canopy",
            "the retaining wall",
            "the MEP layout",
        ],
        "high": [
            "drawing for {i} clashes with services",
            "{i} redesigned by the consultant",
            "no approved drawing for {i}",
            "{i} levels wrong on the drawing",
            "{i} detail missing completely",
            "consultant put {i} on hold",
        ],
        "medium": [
            "waiting for clarification on {i}",
            "RFI on {i} not answered",
            "{i} dims differ between drawings",
            "revised drawing for {i} not received",
            "client wants to change {i}",
            "{i} section unclear",
        ],
        "low": [
            "small note missing on {i} drawing",
            "{i} finish to be confirmed",
            "query on {i}, not urgent",
            "{i} drawing has an old revision number",
            "colour for {i} pending",
        ],
    },
    "quality": {
        "items": [
            "concrete",
            "plaster",
            "brickwork",
            "tiling",
            "screed",
            "welds",
            "waterproofing",
            "rebar",
            "formwork",
            "paintwork",
            "blockwork",
            "skim coat",
            "ceiling boards",
            "door fixing",
            "kerbs",
        ],
        "high": [
            "{i} failed the test",
            "{i} rejected by the consultant",
            "{i} must be broken out and redone",
            "serious defects in {i}",
            "{i} cracked badly",
            "{i} leaking through",
        ],
        "medium": [
            "{i} needs touching up",
            "defects in {i}",
            "{i} not to spec",
            "{i} partly rejected",
            "{i} uneven",
            "{i} with honeycombs",
            "{i} out of plumb",
        ],
        "low": [
            "minor marks on {i}",
            "small patch of {i} to clean",
            "{i} slightly off but within tolerance",
            "snag on {i} noted",
            "hairline crack in {i}",
        ],
    },
    "other": {
        "items": [
            "the police",
            "the council",
            "the neighbours",
            "the water board",
            "the electricity board",
            "the client",
            "the bank",
            "the transporter",
            "the local authority",
            "the landowner",
            "the residents",
            "the traffic police",
            "the fire department",
            "head office",
        ],
        "high": [
            "{i} stopped work on site",
            "{i} closed our access road",
            "{i} ordered us to halt work",
            "{i} cut off the supply",
            "{i} sealed the site",
        ],
        "medium": [
            "{i} complained",
            "waiting for {i} to approve",
            "{i} visit took the morning",
            "{i} delayed our paperwork",
            "{i} restricted lorry movements",
            "{i} asked us to stop the noise",
        ],
        "low": [
            "{i} called about the boundary",
            "{i} wants a meeting",
            "letter from {i} to answer",
            "{i} asked for an update",
            "{i} visited briefly",
        ],
    },
}

ABBREVIATIONS = {
    "delivered": "delivrd",
    "received": "recvd",
    "workers": "wrkrs",
    "material": "matl",
    "tomorrow": "tmrw",
    "because": "bcoz",
    "please": "pls",
    "morning": "mrng",
    "without": "w/o",
    "and": "&",
    "concrete": "conc",
    "drawing": "drwg",
    "again": "agn",
    "hours": "hrs",
    "waiting": "waitng",
    "the ": "",
    "supplier": "suplier",
    "approve": "aprove",
}
SINHALA = {"today": "ada", "tomorrow": "heta", "no ": "naha ", "not ": "naha ", "came": "awa"}


def noisy(text: str, rng: random.Random) -> str:
    """Make a clean sentence read like a quick note from site."""
    if rng.random() < 0.65:
        text = text.lower()
    if rng.random() < 0.4:
        text = text.replace("'", "")
    if rng.random() < 0.35:
        for word, short in ABBREVIATIONS.items():
            if rng.random() < 0.4:
                text = re.sub(
                    rf"\b{re.escape(word.strip())}\b" + (" " if word.endswith(" ") else ""), short, text
                )
    if rng.random() < 0.08:
        for word, local in SINHALA.items():
            text = text.replace(word, local)
    for _ in range(2):
        if rng.random() < 0.2 and len(text) > 12:  # typo: swap or drop a letter
            i = rng.randrange(1, len(text) - 2)
            if text[i].isalpha() and text[i + 1].isalpha():
                text = (
                    text[:i] + text[i + 1] + text[i] + text[i + 2 :]
                    if rng.random() < 0.5
                    else text[:i] + text[i + 1 :]
                )
    if rng.random() < 0.2:
        text = text.rstrip(".") + rng.choice([".", "!!", " ..", "", "!", " pls check"])
    return re.sub(r"\s+", " ", text).strip(" ,-;")


def compose(category: str, base: str, template: str, final: str, rng: random.Random) -> str:
    """One sentence: event (+ repetition) (+ consequence) (+ place/time), in a few word orders."""
    bank = BANK[category]
    core = template.format(i=rng.choice(bank["items"]))
    if LEVELS.index(final) > LEVELS.index(base):  # repetition raised the severity
        repeat = rng.choice(REPEAT)
        core = f"{repeat} {core}" if rng.random() < 0.25 else f"{core} {repeat}"
    where = rng.choice(
        [rng.choice(PLACES), rng.choice(TIMES), f"{rng.choice(PLACES)} {rng.choice(TIMES)}", ""]
    )
    consequence = rng.choice(CONSEQUENCE[final]) if rng.random() < 0.55 else ""
    order = rng.random()
    if order < 0.5:
        parts = [core, where, consequence]
    elif order < 0.75:
        parts = [where, core, consequence]
    else:
        parts = [consequence, core, where] if consequence else [core, where]
    joiner = rng.choice([", ", " - ", "; ", ". "])
    kept = [p for p in parts if p]
    text = joiner.join(kept)
    if consequence and kept[-1] == consequence and len(kept) > 1 and rng.random() < 0.3:
        text = joiner.join(kept[:-1]) + " so " + consequence  # "... so work stopped"
    return noisy(text[0].upper() + text[1:], rng)


def normal(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def main() -> int:
    rng = random.Random(SEED)  # noqa: S311 - reproducible synthetic data, not security
    with (DATA / "test_handwritten.csv").open(encoding="utf-8") as handle:
        test = {normal(row["text"]) for row in csv.DictReader(handle)}
    # Hold out a fifth of each category's event templates for validation.
    templates = [(c, s, t) for c, bank in BANK.items() for s in LEVELS for t in bank[s]]
    val_templates = set()
    for category in BANK:
        own = [x for x in templates if x[0] == category]
        rng.shuffle(own)
        val_templates.update(own[: max(2, round(len(own) * VAL_TEMPLATE_SHARE))])

    weights = {"high": 0.35, "medium": 0.4, "low": 0.25}
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for category in BANK:
        made = 0
        while made < PER_CATEGORY:
            final = rng.choices(LEVELS, weights=list(weights.values()))[0]
            # Reach the final severity either directly or via a lower base plus repetition.
            base = final if final == "low" or rng.random() < 0.75 else LEVELS[LEVELS.index(final) - 1]
            template = rng.choice(BANK[category][base])
            text = compose(category, base, template, final, rng)
            key = normal(text)
            if key in seen or key in test or len(key) < 4:
                continue
            seen.add(key)
            split = "val" if (category, base, template) in val_templates else "train"
            rows.append({"text": text, "category": category, "severity": final, "split": split})
            made += 1
    rng.shuffle(rows)
    for split in ("train", "val"):
        part = [{k: r[k] for k in ("text", "category", "severity")} for r in rows if r["split"] == split]
        with (DATA / f"{split}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["text", "category", "severity"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(part)
        print(f"{split}: {len(part)} sentences")
    print("None of them is in the hand-written test set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
