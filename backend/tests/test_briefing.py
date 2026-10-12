"""Phase 11: the daily briefing's writers (rules and model) and the Claude client, without a database."""

import json
from datetime import date
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from app.ai import briefing as writer
from app.integrations import llm
from app.integrations.llm import ClaudeBriefingLLM, LLMUnavailableError
from tests.conftest import make_settings

NO_ISSUES = writer.IssueFacts(total_7d=0, high_7d=0, by_category_7d={})


def project(code: str = "HR-1", **overrides: Any) -> writer.ProjectFacts:
    values: dict[str, Any] = {
        "code": code,
        "name": f"Project {code}",
        "status": "active",
        "risk": None,
        "planned_pct": None,
        "actual_pct": None,
        "report_due_today": False,
        "report_filed_today": False,
        "issues": NO_ISSUES,
        "stop_work_open": 0,
        "pour_rain_tasks": 0,
        "sections_over_budget": None,
    }
    values.update(overrides)
    return writer.ProjectFacts(**values)


def risk(score: int = 78, level: str = "high", **overrides: Any) -> writer.RiskFacts:
    values: dict[str, Any] = {
        "score": score,
        "level": level,
        "score_range": writer.Range(low=score - 6, high=score + 6),
        "change_7d": 0,
        "delay_days": 18.0,
        "delay_range": writer.Range(low=10.2, high=27.4),
        "overrun_pct": None,
        "overrun_range": None,
    }
    values.update(overrides)
    return writer.RiskFacts(**values)


def facts(*projects: writer.ProjectFacts, sees_cost: bool = True, **waiting: int) -> writer.Facts:
    counts = {"material_requests": 0, "purchase_orders": 0, "claims": 0, "variations": 0, **waiting}
    return writer.Facts(
        date=date(2026, 10, 12),
        role="project_manager",
        sees_cost=sees_cost,
        projects=list(projects),
        waiting_for_you=writer.WaitingFacts(**counts),
    )


# --- The facts are allow-listed -------------------------------------------------------------------------


def test_facts_refuse_any_field_they_do_not_declare() -> None:
    with pytest.raises(ValidationError):
        writer.ProjectFacts(**{**project().model_dump(), "problems": "Cement late, Kamal hurt his hand"})
    with pytest.raises(ValidationError):
        writer.Facts(**{**facts().model_dump(), "author": "Kamal Perera"})


def test_project_codes_are_codes_not_free_text() -> None:
    with pytest.raises(ValidationError):
        project("Kamal said the slab cracked")


def test_canonical_json_is_stable() -> None:
    a = facts(project("HR-1"), project("KD-2"))
    assert a.canonical_json() == facts(project("HR-1"), project("KD-2")).canonical_json()
    assert json.loads(a.canonical_json())["projects"][1]["code"] == "KD-2"


# --- The rule-based writer ------------------------------------------------------------------------------


def test_rules_put_stop_work_and_high_risk_first_with_likely_ranges() -> None:
    f = facts(
        project("HR-1", risk=risk(78), stop_work_open=2),
        project("KD-2", risk=risk(35, "low", delay_days=0.0)),
        material_requests=2,
        claims=1,
    )
    bullets = writer.write_rules(f)
    assert writer.MIN_BULLETS <= len(bullets) <= writer.MAX_BULLETS
    assert bullets[0].text.startswith("Stop-work is in force (BR-11): 2 open flags on HR-1")
    assert bullets[1].text == (
        "1 project at high risk (BR-10): HR-1 (score 78, likely 72 to 84; "
        "forecast 18 days late, likely 10 to 27)."
    )
    assert bullets[2].text == "3 items waiting for you: 2 material requests, 1 progress claim."
    assert [s.model_dump() for s in bullets[0].sources] == [{"kind": "stop_work", "count": 2}]
    assert [s.model_dump() for s in bullets[1].sources] == [{"kind": "risk", "count": 1}]


def test_rules_cover_rain_reports_progress_issues_and_cost() -> None:
    issues = writer.IssueFacts(total_7d=4, high_7d=1, by_category_7d={"material_delay": 3, "labour": 1})
    f = facts(
        project("HR-1", pour_rain_tasks=2, report_due_today=True, planned_pct=50.0, actual_pct=40.5),
        project(
            "KD-2", report_due_today=True, report_filed_today=True, issues=issues, sections_over_budget=2
        ),
    )
    texts = [b.text for b in writer.write_rules(f)]
    assert texts == [
        "Heavy rain is forecast on planned concrete pours (BR-06): HR-1 (2 pours). Check the pour dates.",
        "1 of 2 daily reports not filed yet today (BR-07): HR-1.",
        "Behind plan: HR-1 9.5 points.",
        "4 issues confirmed in the last 7 days, most often material delay (3); 1 high severity.",
        "Cost sections forecast more than 5% over budget: KD-2 (2 sections).",
    ]


def test_rules_leave_cost_out_for_roles_that_do_not_see_it() -> None:
    f = facts(project("HR-1", sections_over_budget=3), sees_cost=False)
    assert not any("budget" in b.text for b in writer.write_rules(f))


def test_rules_mention_a_sharp_rise_in_risk() -> None:
    f = facts(project("HR-1", risk=risk(62, "medium", change_7d=14)))
    assert "Risk is rising this week: HR-1 up 14 to 62." in [b.text for b in writer.write_rules(f)]


def test_a_quiet_day_still_gives_three_calm_bullets() -> None:
    f = facts(
        project("HR-1", risk=risk(30, "low", delay_days=0.2), report_due_today=True, report_filed_today=True)
    )
    texts = [b.text for b in writer.write_rules(f)]
    assert texts == [
        "No project is at high risk. Highest: HR-1 (score 30, likely 24 to 36; forecast on time).",
        "All 1 daily report due today are filed.",
        "No stop-work flags are open.",
    ]


def test_no_projects() -> None:
    assert [b.text for b in writer.write_rules(facts())] == ["No open projects on your sites yet."]


def test_rules_never_give_more_than_five_bullets() -> None:
    busy = writer.IssueFacts(total_7d=1, high_7d=0, by_category_7d={"labour": 1})
    f = facts(
        project(
            "HR-1", risk=risk(80), stop_work_open=1, pour_rain_tasks=1, report_due_today=True,
            planned_pct=60.0, actual_pct=40.0, issues=busy, sections_over_budget=1,
        ),
        project("KD-2", risk=risk(50, "medium", change_7d=20)),
        variations=1,
    )  # fmt: skip
    assert len(writer.write_rules(f)) == writer.MAX_BULLETS


def test_source_counts_follow_the_projects_a_bullet_names() -> None:
    issues = writer.IssueFacts(total_7d=3, high_7d=0, by_category_7d={"labour": 3})
    f = facts(project("HR-1", issues=issues, risk=risk()), project("KD-2", issues=issues), claims=2)
    assert writer.count_source(f, "issues", ["HR-1"]) == 3
    assert writer.count_source(f, "issues", []) == 6  # no project named: all of them
    assert writer.count_source(f, "risk", []) == 1
    assert writer.count_source(f, "approvals", ["HR-1"]) == 2
    assert writer.count_source(f, "cost", []) == 0


# --- The model's answer is checked ----------------------------------------------------------------------


def answer(*bullets: dict[str, Any]) -> str:
    return json.dumps({"bullets": list(bullets)})


def b(
    text: str = "HR-1 is at high risk (BR-10).",
    projects: list[str] | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "projects": ["HR-1"] if projects is None else projects,
        "sources": sources or ["risk"],
    }


def test_parse_llm_counts_sources_itself() -> None:
    f = facts(project("HR-1", risk=risk()), project("KD-2", risk=risk(40, "medium")))
    bullets = writer.parse_llm(f, answer(b(), b("Both projects are scored.", [], ["risk", "risk"]), b()))
    assert bullets[0].sources[0].count == 1
    assert bullets[1].sources == [writer.Source(kind="risk", count=2)]  # duplicates collapse


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        answer(b(), b()),  # too few
        answer(*[b()] * 6),  # too many
        answer(b(), b(), b(projects=["XX-9"])),  # a project the reader cannot see
        answer(b(), b(), b(sources=["gossip"])),
        answer(b(), b(), b(text="short")),
        answer(b(), b(), b(text="x" * 301)),
        json.dumps({"bullets": [b(), b(), b()], "extra": 1}),
    ],
)
def test_parse_llm_rejects_answers_outside_the_rules(raw: str) -> None:
    with pytest.raises(writer.InvalidAnswerError):
        writer.parse_llm(facts(project("HR-1")), raw)


def test_output_schema_limits_codes_to_the_readers_projects() -> None:
    schema = writer.output_schema(["HR-1", "KD-2"])
    item = schema["properties"]["bullets"]["items"]
    assert item["properties"]["projects"]["items"] == {"type": "string", "enum": ["HR-1", "KD-2"]}
    assert item["additionalProperties"] is False
    assert set(item["properties"]["sources"]["items"]["enum"]) == set(writer.SOURCE_KINDS)


# --- The Claude client ----------------------------------------------------------------------------------


def message(text: str = '{"bullets": []}', stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def client_with(handler: Any) -> ClaudeBriefingLLM:
    transport = httpx2.MockTransport(handler)
    return ClaudeBriefingLLM(
        "test-key", "claude-haiku-5-5", 5.0, http_client=httpx2.Client(transport=transport)
    )


def test_client_sends_the_configured_model_with_a_json_schema() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=message('{"bullets": ["ok"]}'))

    text = client_with(handler).complete("system text", "facts", {"type": "object"})
    assert text == '{"bullets": ["ok"]}'
    body = seen[0]
    assert body["model"] == "claude-haiku-5-5"
    assert body["system"] == "system text"
    assert body["messages"] == [{"role": "user", "content": "facts"}]
    assert body["thinking"] == {"type": "disabled"}
    assert body["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx2.Response(200, json=message(stop_reason="refusal")), "refusal"),
        (httpx2.Response(200, json=message(stop_reason="max_tokens")), "truncated"),
        (httpx2.Response(200, json=message(text="")), "empty"),
        (
            httpx2.Response(
                401, json={"type": "error", "error": {"type": "authentication_error", "message": "x"}}
            ),
            "AuthenticationError",
        ),
        (
            httpx2.Response(
                429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "x"}}
            ),
            "RateLimitError",
        ),
        (
            httpx2.Response(
                529, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}}
            ),
            "OverloadedError",
        ),
    ],
)
def test_client_turns_every_failure_into_unavailable(response: httpx2.Response, reason: str) -> None:
    llm_client = client_with(lambda request: response)
    with pytest.raises(LLMUnavailableError) as caught:
        llm_client.complete("s", "p", {"type": "object"})
    assert str(caught.value) == reason or isinstance(caught.value.__cause__, anthropic.APIStatusError)


def test_client_turns_a_network_failure_into_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(LLMUnavailableError) as caught:
        client_with(handler).complete("s", "p", {"type": "object"})
    assert str(caught.value) == "APIConnectionError"


def test_no_key_means_no_client() -> None:
    assert llm.from_settings(make_settings()) is None
    assert llm.from_settings(make_settings(anthropic_api_key=SecretStr("   "))) is None
    client = llm.from_settings(
        make_settings(anthropic_api_key=SecretStr("sk-test"), briefing_model="claude-sonnet-5-5")
    )
    assert client is not None
    assert client.model == "claude-sonnet-5-5"


def test_the_model_name_is_checked() -> None:
    with pytest.raises(ValidationError):
        make_settings(briefing_model="Claude Haiku; rm -rf")


def test_tied_issue_kinds_are_not_called_most_often() -> None:
    issues = writer.IssueFacts(total_7d=3, high_7d=0, by_category_7d={"weather": 1, "labour": 1, "safety": 1})
    texts = [b.text for b in writer.write_rules(facts(project("HR-1", issues=issues)))]
    assert "3 issues confirmed in the last 7 days, spread across 3 kinds." in texts
