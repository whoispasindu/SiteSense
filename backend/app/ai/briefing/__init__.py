"""The daily briefing (Phase 11): what needs attention today, in 3 to 5 bullets with source counts.

Two writers share one input:

- ``Facts``: an allow-listed summary of the reader's projects. It holds only numbers, rule IDs,
  project codes and project names, and enumerated words (statuses, risk levels, issue categories).
  Every model forbids extra fields, so nothing else can be added by mistake: no report text, no
  comments, no people's names, no site, supplier or task names. This is the only thing the language
  model ever sees.
- ``write_rules``: plain sentences from fixed templates. Always available; used when no API key is
  set and whenever the model fails, refuses or answers outside the schema.
- ``parse_llm``: checks the model's answer (3 to 5 bullets, known project codes and source kinds,
  short text) and fills in the source counts itself. The model never states counts.

Forecasts always carry their likely range ("18 days late, likely 10 to 27").
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

SourceKind = Literal["risk", "programme", "reports", "issues", "stop_work", "weather", "approvals", "cost"]
SOURCE_KINDS: tuple[SourceKind, ...] = (
    "risk",
    "programme",
    "reports",
    "issues",
    "stop_work",
    "weather",
    "approvals",
    "cost",
)
Category = Literal["material_delay", "labour", "weather", "equipment", "safety", "design", "quality", "other"]
MIN_BULLETS, MAX_BULLETS = 3, 5
MAX_TEXT = 300
BEHIND_POINTS = 2.0

Code = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9-]{1,23}$")]
ProjectName = Annotated[str, StringConstraints(min_length=1, max_length=160)]
Count = Annotated[int, Field(ge=0, le=100_000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Range(_Strict):
    low: float
    high: float


class RiskFacts(_Strict):
    score: Annotated[int, Field(ge=0, le=100)]
    level: Literal["low", "medium", "high"]
    score_range: Range | None
    change_7d: int | None  # points since the score a week earlier; None without one
    delay_days: float
    delay_range: Range | None
    overrun_pct: float | None  # cost roles only
    overrun_range: Range | None


class IssueFacts(_Strict):
    total_7d: Count
    high_7d: Count
    by_category_7d: dict[Category, Count]


class ProjectFacts(_Strict):
    code: Code
    name: ProjectName
    status: Literal["planning", "active", "on_hold", "completed", "cancelled"]
    risk: RiskFacts | None
    planned_pct: float | None  # None without a programme
    actual_pct: float | None
    report_due_today: bool
    report_filed_today: bool
    issues: IssueFacts
    stop_work_open: Count  # BR-11
    pour_rain_tasks: Count  # BR-06: pours with heavy rain forecast in their window
    sections_over_budget: Count | None  # cost roles only


class WaitingFacts(_Strict):
    material_requests: Count
    purchase_orders: Count  # approved requests ready to order (procurement)
    claims: Count
    variations: Count

    @property
    def total(self) -> int:
        return self.material_requests + self.purchase_orders + self.claims + self.variations


class Facts(_Strict):
    date: date
    role: Literal["project_manager", "quantity_surveyor", "site_engineer", "procurement_officer"]
    sees_cost: bool
    projects: list[ProjectFacts]
    waiting_for_you: WaitingFacts

    def canonical_json(self) -> str:
        """Sorted, compact JSON: the same facts always give the same text (and hash)."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class Source(BaseModel):
    kind: SourceKind
    count: int


class Bullet(BaseModel):
    text: str
    projects: list[str]
    sources: list[Source]


# --- Source counts (always by the server) ---------------------------------------------------------------


def _cited(facts: Facts, codes: Iterable[str]) -> list[ProjectFacts]:
    wanted = set(codes)
    return [p for p in facts.projects if p.code in wanted] if wanted else list(facts.projects)


def count_source(facts: Facts, kind: SourceKind, codes: Iterable[str]) -> int:
    """How many records of ``kind`` the bullet rests on, among the projects it names (all if none)."""
    projects = _cited(facts, codes)
    match kind:
        case "risk":
            return sum(1 for p in projects if p.risk is not None)
        case "programme":
            return sum(1 for p in projects if p.planned_pct is not None)
        case "reports":
            return sum(1 for p in projects if p.report_due_today)
        case "issues":
            return sum(p.issues.total_7d for p in projects)
        case "stop_work":
            return sum(p.stop_work_open for p in projects)
        case "weather":
            return sum(p.pour_rain_tasks for p in projects)
        case "approvals":
            return facts.waiting_for_you.total
        case "cost":
            return sum(1 for p in projects if p.sections_over_budget is not None)


def bullet(facts: Facts, text: str, codes: list[str], kinds: list[SourceKind]) -> Bullet:
    return Bullet(
        text=text,
        projects=codes,
        sources=[Source(kind=k, count=count_source(facts, k, codes)) for k in dict.fromkeys(kinds)],
    )


# --- The rule-based writer ------------------------------------------------------------------------------


def _n(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


def _days(value: float) -> str:
    return f"{round(value)} day{'' if round(value) == 1 else 's'}"


def _likely(r: Range | None, unit: str = "") -> str:
    return f", likely {round(r.low)}{unit} to {round(r.high)}{unit}" if r is not None else ""


def _join(items: list[str], limit: int = 3) -> str:
    shown = items[:limit]
    more = len(items) - len(shown)
    text = ", ".join(shown)
    return text + (f" and {more} more" if more > 0 else "")


def _risk_line(p: ProjectFacts) -> str:
    assert p.risk is not None
    r = p.risk
    late = f"{_days(r.delay_days)} late{_likely(r.delay_range)}" if r.delay_days >= 0.5 else "on time"
    return f"{p.code} (score {r.score}{_likely(r.score_range)}; forecast {late})"


def write_rules(facts: Facts) -> list[Bullet]:
    """3 to 5 bullets from fixed templates, most urgent first."""
    out: list[Bullet] = []
    projects = facts.projects

    stopped = [p for p in projects if p.stop_work_open]
    if stopped:
        flags = sum(p.stop_work_open for p in stopped)
        text = (
            f"Stop-work is in force (BR-11): {_n(flags, 'open flag')} on "
            f"{_join([p.code for p in stopped])}. Stopped tasks take no progress until cleared."
        )
        out.append(bullet(facts, text, [p.code for p in stopped], ["stop_work"]))

    high = sorted(
        (p for p in projects if p.risk is not None and p.risk.level == "high"),
        key=lambda p: -(p.risk.score if p.risk else 0),
    )
    if high:
        text = (
            f"{_n(len(high), 'project')} at high risk (BR-10): "
            + "; ".join(_risk_line(p) for p in high[:3])
            + "."
        )
        out.append(bullet(facts, text, [p.code for p in high], ["risk"]))

    rising = [p for p in projects if p.risk is not None and (p.risk.change_7d or 0) >= 10 and p not in high]
    if rising:
        parts = [f"{p.code} up {p.risk.change_7d} to {p.risk.score}" for p in rising if p.risk is not None]
        out.append(
            bullet(facts, f"Risk is rising this week: {_join(parts)}.", [p.code for p in rising], ["risk"])
        )

    rain = [p for p in projects if p.pour_rain_tasks]
    if rain:
        parts = [f"{p.code} ({_n(p.pour_rain_tasks, 'pour')})" for p in rain]
        text = (
            f"Heavy rain is forecast on planned concrete pours (BR-06): {_join(parts)}. Check the pour dates."
        )
        out.append(bullet(facts, text, [p.code for p in rain], ["weather", "programme"]))

    w = facts.waiting_for_you
    if w.total:
        parts = [
            _n(w.material_requests, "material request") if w.material_requests else "",
            _n(w.purchase_orders, "approved request") + " to order" if w.purchase_orders else "",
            _n(w.claims, "progress claim") if w.claims else "",
            _n(w.variations, "variation") if w.variations else "",
        ]
        text = f"{_n(w.total, 'item')} waiting for you: {_join([x for x in parts if x], 4)}."
        out.append(bullet(facts, text, [], ["approvals"]))

    missing = [p for p in projects if p.report_due_today and not p.report_filed_today]
    if missing:
        due = sum(1 for p in projects if p.report_due_today)
        text = (
            f"{len(missing)} of {_n(due, 'daily report')} not filed yet today (BR-07): "
            f"{_join([p.code for p in missing])}."
        )
        out.append(bullet(facts, text, [p.code for p in missing], ["reports"]))

    behind = sorted(
        (
            p
            for p in projects
            if p.planned_pct is not None
            and p.actual_pct is not None
            and p.actual_pct - p.planned_pct < -BEHIND_POINTS
        ),
        key=lambda p: (p.actual_pct or 0) - (p.planned_pct or 0),
    )
    if behind:
        parts = [f"{p.code} {abs((p.actual_pct or 0) - (p.planned_pct or 0)):.1f} points" for p in behind]
        out.append(bullet(facts, f"Behind plan: {_join(parts)}.", [p.code for p in behind], ["programme"]))

    issue_total = sum(p.issues.total_7d for p in projects)
    if issue_total:
        by_category: dict[str, int] = {}
        for p in projects:
            for category, count in p.issues.by_category_7d.items():
                by_category[category] = by_category.get(category, 0) + count
        top_count = max(by_category.values())
        tied = sorted(c for c, n in by_category.items() if n == top_count)
        if len(tied) == 1:
            kinds = f"most often {tied[0].replace('_', ' ')} ({top_count})"
        else:
            kinds = f"spread across {len(by_category)} kinds"
        high_count = sum(p.issues.high_7d for p in projects)
        text = f"{_n(issue_total, 'issue')} confirmed in the last 7 days, {kinds}" + (
            f"; {high_count} high severity." if high_count else "."
        )
        cited = [p.code for p in projects if p.issues.total_7d]
        out.append(bullet(facts, text, cited, ["issues"]))

    if facts.sees_cost:
        over = [p for p in projects if p.sections_over_budget]
        if over:
            parts = [f"{p.code} ({_n(p.sections_over_budget or 0, 'section')})" for p in over]
            text = f"Cost sections forecast more than 5% over budget: {_join(parts)}."
            out.append(bullet(facts, text, [p.code for p in over], ["cost"]))

    # Calm news fills the briefing to at least three bullets.
    if len(out) < MIN_BULLETS and not high and any(p.risk is not None for p in projects):
        top = max((p for p in projects if p.risk is not None), key=lambda p: p.risk.score if p.risk else 0)
        out.append(
            bullet(facts, f"No project is at high risk. Highest: {_risk_line(top)}.", [top.code], ["risk"])
        )
    if len(out) < MIN_BULLETS and any(p.report_due_today for p in projects) and not missing:
        due = sum(1 for p in projects if p.report_due_today)
        out.append(bullet(facts, f"All {_n(due, 'daily report')} due today are filed.", [], ["reports"]))
    if len(out) < MIN_BULLETS and not stopped and projects:
        out.append(bullet(facts, "No stop-work flags are open.", [], ["stop_work"]))
    if len(out) < MIN_BULLETS and not w.total:
        out.append(bullet(facts, "Nothing is waiting for your approval.", [], ["approvals"]))
    if len(out) < MIN_BULLETS and not rain and projects:
        out.append(bullet(facts, "No heavy rain is forecast on planned pours.", [], ["weather"]))
    if not projects:
        out = [bullet(facts, "No open projects on your sites yet.", [], [])]
    return out[:MAX_BULLETS]


# --- The language model's part --------------------------------------------------------------------------

SYSTEM = """You write the daily briefing for a construction company's project dashboard.
You receive structured facts as JSON: project codes and names, risk scores with likely ranges, \
progress, report and issue counts, rule IDs, and counts of items waiting for the reader.
Write 3 to 5 bullets on what needs attention today, most urgent first.
Rules:
- Use only the facts given. Do not invent names, causes, dates or numbers.
- Whenever you give a forecast (delay days, cost overrun, risk score), give its likely range with it, \
for example "18 days late, likely 10 to 27".
- Refer to projects by code. Mention rule IDs (BR-06 heavy rain on a pour, BR-07 missing report, \
BR-10 high risk, BR-11 stop-work) where they apply.
- Plain, short sentences in British English, at most 280 characters per bullet. No greetings.
- For each bullet list the project codes it is about and the kinds of facts it uses."""


def output_schema(codes: list[str]) -> dict[str, Any]:
    """The JSON shape the model must answer in. Project codes are limited to the reader's own."""
    code_items: dict[str, Any] = {"type": "string", "enum": codes} if codes else {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "bullets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "projects": {"type": "array", "items": code_items},
                        "sources": {"type": "array", "items": {"type": "string", "enum": list(SOURCE_KINDS)}},
                    },
                    "required": ["text", "projects", "sources"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["bullets"],
        "additionalProperties": False,
    }


def prompt(facts: Facts) -> str:
    return "Today's facts:\n" + facts.canonical_json()


class _LLMBullet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=MAX_TEXT)]
    projects: list[str] = Field(max_length=20)
    sources: list[SourceKind] = Field(max_length=len(SOURCE_KINDS))


class _LLMAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bullets: list[_LLMBullet] = Field(min_length=MIN_BULLETS, max_length=MAX_BULLETS)


class InvalidAnswerError(ValueError):
    pass


def parse_llm(facts: Facts, raw: str) -> list[Bullet]:
    """The model's bullets, checked, with server-counted sources. Raises ``InvalidAnswerError``."""
    try:
        answer = _LLMAnswer.model_validate_json(raw)
    except ValidationError as exc:
        raise InvalidAnswerError("schema") from exc
    known = {p.code for p in facts.projects}
    out = []
    for b in answer.bullets:
        if not set(b.projects) <= known:
            raise InvalidAnswerError("unknown project")
        codes = list(dict.fromkeys(b.projects))
        out.append(bullet(facts, b.text, codes, list(b.sources)))
    return out
