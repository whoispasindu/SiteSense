"""Phase 11: what reaches the language model, and the rule-based fallback.

The briefing may send the model only structured facts: scores, ranges, counts, project codes and
names, rule IDs. Never report text, comments, or people's names. These tests run the real Claude
client against a fake transport, capture the HTTP request exactly as it would leave the server,
and fail if any of the world's free text or names (``SECRETS``) is in it.
"""

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import briefing as writer
from app.integrations.llm import ClaudeBriefingLLM
from app.models import Briefing
from tests.dashboard_fixtures import SECRETS, World


class FakeClaude:
    """The real SDK client over a fake transport: records each request body, answers from a script."""

    def __init__(self, answer: Callable[[dict[str, Any]], httpx2.Response] | None = None) -> None:
        self.bodies: list[bytes] = []
        self.answer = answer or self.valid_answer
        transport = httpx2.MockTransport(self._handle)
        self.client = ClaudeBriefingLLM(
            "test-key", "claude-haiku-5-5", 5.0, http_client=httpx2.Client(transport=transport)
        )

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(request.content)
        return self.answer(json.loads(request.content))

    @staticmethod
    def valid_answer(body: dict[str, Any]) -> httpx2.Response:
        bullets = [
            {
                "text": "HR-1 is at high risk (BR-10): score 78, likely 71 to 84.",
                "projects": ["HR-1"],
                "sources": ["risk"],
            },
            {
                "text": "Stop-work is in force on HR-1 (BR-11).",
                "projects": ["HR-1"],
                "sources": ["stop_work"],
            },
            {
                "text": "One material request waits for your approval.",
                "projects": [],
                "sources": ["approvals"],
            },
        ]
        return httpx2.Response(200, json=message(json.dumps({"bullets": bullets})))


def message(text: str, stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }  # fmt: skip


@pytest.fixture
def claude(app: FastAPI) -> FakeClaude:
    fake = FakeClaude()
    app.state.briefing_llm = fake.client
    return fake


def briefing(api: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = api.get("/api/v1/briefing/today", headers=headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def sent_facts(body: bytes) -> writer.Facts:
    request = json.loads(body)
    prompt: str = request["messages"][0]["content"]
    return writer.Facts.model_validate_json(prompt.removeprefix("Today's facts:\n"))


# --- Nothing but facts leaves the server -----------------------------------------------------------------


@pytest.mark.parametrize("who", ["pm", "qs", "se", "buyer"])
def test_no_report_text_or_name_reaches_the_model(
    api: TestClient, world: World, claude: FakeClaude, who: str
) -> None:
    member = getattr(world, who)
    result = briefing(api, member.headers)

    assert result["source"] == "ai"
    assert result["label"] == "AI-written"
    assert len(claude.bodies) == 1
    raw = claude.bodies[0].decode()
    # The capture works: the facts the model is allowed to see are there.
    assert "HR-1" in raw
    assert "Havelock Residences" in raw
    for secret in SECRETS:
        assert secret not in raw, f"{secret!r} reached the model"
    assert member.user.email not in raw
    assert str(member.user.id) not in raw
    # The prompt is exactly the allow-listed facts, nothing more.
    sent_facts(claude.bodies[0])


def test_the_request_carries_only_the_fixed_instruction_and_the_facts(
    api: TestClient, world: World, claude: FakeClaude
) -> None:
    briefing(api, world.pm.headers)
    request = json.loads(claude.bodies[0])
    assert set(request) == {"model", "max_tokens", "system", "messages", "thinking", "output_config"}
    assert request["system"] == writer.SYSTEM
    assert len(request["messages"]) == 1
    facts = sent_facts(claude.bodies[0])
    assert [p.code for p in facts.projects] == ["HR-1"]  # the other site's project is not the reader's


def test_the_facts_follow_role_visibility(api: TestClient, world: World, claude: FakeClaude) -> None:
    briefing(api, world.pm.headers)
    briefing(api, world.se.headers)
    pm, se = (sent_facts(body) for body in claude.bodies)

    hr = pm.projects[0]
    assert pm.sees_cost
    assert hr.risk is not None
    assert hr.risk.score == 78
    assert hr.risk.change_7d == 18
    assert hr.risk.overrun_pct == 6.5
    assert hr.sections_over_budget is not None
    assert hr.stop_work_open == 1
    assert hr.issues.total_7d == 2  # the removed suggestion is not an issue
    assert hr.issues.high_7d == 1
    assert pm.waiting_for_you.material_requests == 1

    # A site engineer sees no risk scores and no cost figures, so the model is not told them either.
    assert not se.sees_cost
    assert se.projects[0].risk is None
    assert se.projects[0].sections_over_budget is None
    assert se.waiting_for_you.total == 0


# --- The rule-based fallback -----------------------------------------------------------------------------


def test_without_a_key_everyone_gets_the_rule_based_briefing(
    api: TestClient, app: FastAPI, world: World
) -> None:
    app.state.briefing_llm = None
    result = briefing(api, world.pm.headers)
    assert result["source"] == "rules"
    assert result["label"] == "Rule-based"
    assert result["model"] is None
    assert result["note"] is None
    assert 3 <= len(result["bullets"]) <= 5
    texts = " ".join(b["text"] for b in result["bullets"])
    assert "BR-11" in texts
    assert "likely 71 to 84" in texts  # the forecast comes with its range
    for secret in SECRETS:
        assert secret not in json.dumps(result)


@pytest.mark.parametrize(
    "failure",
    [
        lambda body: httpx2.Response(
            529, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}}
        ),
        lambda body: httpx2.Response(200, json=message("{}", "refusal")),
        lambda body: httpx2.Response(200, json=message('{"bullets": []}')),  # outside the schema
        lambda body: httpx2.Response(
            200,
            json=message(
                '{"bullets": [{"text": "XX-1 is late again.", "projects": ["XX-1"], "sources": []}]}'
            ),
        ),
    ],
)
def test_any_model_failure_falls_back_to_the_rules(
    api: TestClient, app: FastAPI, world: World, failure: Callable[[dict[str, Any]], httpx2.Response]
) -> None:
    app.state.briefing_llm = FakeClaude(failure).client
    result = briefing(api, world.pm.headers)
    assert result["source"] == "rules"
    assert result["label"] == "Rule-based"
    assert result["note"] == "The AI briefing is unavailable just now, so this one is written by fixed rules."
    assert result["bullets"][0]["text"].startswith("Stop-work is in force (BR-11)")


def test_bullets_carry_source_counts_from_the_server(
    api: TestClient, world: World, claude: FakeClaude
) -> None:
    result = briefing(api, world.pm.headers)
    assert result["bullets"][0]["sources"] == [{"kind": "risk", "count": 1}]
    assert result["bullets"][1]["sources"] == [{"kind": "stop_work", "count": 1}]
    assert result["bullets"][2]["sources"] == [{"kind": "approvals", "count": 1}]


# --- Calls to the model are limited ----------------------------------------------------------------------


def test_the_briefing_is_reused_while_the_facts_are_unchanged(
    api: TestClient, db: Session, world: World, claude: FakeClaude
) -> None:
    first = briefing(api, world.pm.headers)
    second = briefing(api, world.pm.headers)
    assert len(claude.bodies) == 1
    assert first == second
    stored = db.scalars(select(Briefing).where(Briefing.user_id == world.pm.user.id)).all()
    assert [(b.source, b.model) for b in stored] == [("ai", "claude-haiku-5-5")]


def age(db: Session, world: World, minutes: int) -> None:
    """Make the stored briefing older (moving the clock would expire the test's sign-in)."""
    for row in db.scalars(select(Briefing).where(Briefing.user_id == world.pm.user.id)):
        row.created_at -= timedelta(minutes=minutes)
    db.commit()


def test_changed_facts_wait_fifteen_minutes_for_a_new_ai_briefing(
    api: TestClient, db: Session, world: World, claude: FakeClaude
) -> None:
    briefing(api, world.pm.headers)
    world.request.status = "approved"  # the approval queue changes
    db.commit()
    age(db, world, 14)
    briefing(api, world.pm.headers)
    assert len(claude.bodies) == 1
    age(db, world, 2)
    briefing(api, world.pm.headers)
    assert len(claude.bodies) == 2
    assert sent_facts(claude.bodies[1]).waiting_for_you.material_requests == 0


def test_after_a_failure_the_model_is_tried_again_ten_minutes_later(
    api: TestClient, app: FastAPI, db: Session, world: World
) -> None:
    calls = {"n": 0}

    def flaky(body: dict[str, Any]) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] <= 2:  # the first request and the SDK's one retry
            return httpx2.Response(
                500, json={"type": "error", "error": {"type": "api_error", "message": "x"}}
            )
        return FakeClaude.valid_answer(body)

    fake = FakeClaude(flaky)
    app.state.briefing_llm = fake.client
    assert briefing(api, world.pm.headers)["source"] == "rules"
    assert calls["n"] == 2  # the request and the SDK's one retry
    retries = calls["n"]
    assert briefing(api, world.pm.headers)["source"] == "rules"
    assert calls["n"] == retries  # not again within ten minutes
    age(db, world, 11)
    assert briefing(api, world.pm.headers)["source"] == "ai"


def test_briefings_are_private_to_each_reader(
    api: TestClient, db: Session, world: World, claude: FakeClaude
) -> None:
    briefing(api, world.pm.headers)
    briefing(api, world.qs.headers)
    owners = set(db.scalars(select(Briefing.user_id)))
    assert owners == {world.pm.user.id, world.qs.user.id}
    assert len(claude.bodies) == 2


def test_clients_and_admins_have_no_briefing(api: TestClient, world: World, team: Callable[..., Any]) -> None:
    from app.core.permissions import Role

    for role in (Role.CLIENT, Role.ADMIN):
        who = team(role, sites=[world.site])
        assert api.get("/api/v1/briefing/today", headers=who.headers).status_code == 403
