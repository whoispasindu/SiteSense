# Labelling guide: site report issues

Each example is **one sentence** from the "Problems" box of a daily site report, with one
**category** and one **severity**. A report with several problems is split into sentences, and each
sentence is tagged on its own. If a sentence mixes two issues, label the one that stops or slows the
work most; if it is still unclear, the one mentioned first.

## Categories

| Label | Use for | Examples | Not this |
| --- | --- | --- | --- |
| `material_delay` | Materials late, short, not delivered, wrong quantity | "Cement not delivered again", "Only half the blocks came", "Rebar lorry did not turn up" | Wrong *grade* or damaged material (`quality`) |
| `labour` | People: crew short, absent, strike, skills missing, subcontractor not on site | "Only 12 masons turned up", "Tiling subcontractor no show" | Injured worker (`safety`) |
| `weather` | Rain, heat, wind, flooding stopping or slowing work | "Heavy rain from 10 am, pour postponed" | Water leak from a pipe (`quality`) |
| `equipment` | Plant and tools: breakdown, unavailable, fuel, power for plant | "Crane down with a hydraulic leak", "Mixer broke at noon" | Unsafe scaffold (`safety`) |
| `safety` | Injuries, near misses, unsafe conditions or behaviour, missing PPE, stop-work events | "Worker fell from scaffold", "No harnesses on level 6" | Rain making a slab slippery (`weather` unless it caused an incident) |
| `design` | Drawings, details, RFIs, clashes, design changes, missing information from the consultant | "Beam detail clashes with duct", "Still waiting for revised stair drawings" | Work built wrong by the crew (`quality`) |
| `quality` | Defects, rework, failed tests or inspections, wrong grade, damaged materials | "Cube test failed", "Honeycombing on column C4, needs repair" | |
| `other` | Anything else: access, permits, neighbours, utilities, client visits, admin | "Police stopped deliveries at the gate", "Water board cut supply" | |

## Severity

| Label | Meaning | Signals |
| --- | --- | --- |
| `high` | Work stopped or will stop; someone hurt or at real risk; a critical activity lost (a pour cancelled); a **repeated** failure | "stopped", "whole day lost", "cancelled", "again", "third time", "injured", "collapsed" |
| `medium` | Work slowed or partly affected; a delay of hours; needs follow-up soon | "delayed by 3 hours", "slowed", "half the crew idle", "waiting since morning" |
| `low` | Minor, noted, or already resolved; a possible future problem | "slightly late", "sorted by noon", "minor", "keep an eye on" |

Repetition raises severity by one step: "cement late" is medium, "cement late again" is high. Any
injury is high. A near miss with no injury is medium unless work was stopped.

## Text as it is written on site

Keep the writer's wording: lower case, missing apostrophes ("didnt"), abbreviations ("matl", "pls",
"wrkrs"), typos, and Sinhala or Tamil words written in English letters (for example "naha" for "no",
"ada" for "today", "baas" for foreman). Do not correct them; the model must learn to read them.

## Names

Replace people's names with `[PERSON]` before a sentence is stored or sent anywhere. Company names
(suppliers, subcontractors) may stay.

## Data in this repository

- `data/train.csv`, `data/val.csv`: **synthetic**, produced by `generate.py` from phrase banks and
  templates with the noise above. Used for training and tuning only.
- `data/test_handwritten.csv`: **written by hand, separately from the templates**, in varied wording
  that the templates do not produce. Never used for training or tuning; it is the only score that
  counts. No real contractor data is included yet.
