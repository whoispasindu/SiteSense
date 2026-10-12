"""The language model behind the AI daily briefing (Phase 11): Claude, through the official SDK.

The only module that talks to the model. It receives a fixed instruction and a JSON document of
structured facts (``app.ai.briefing.Facts``: scores, ranges, counts, project codes and names, rule
IDs) and returns the model's JSON answer. It never receives report text, comments or people's
names; ``tests/test_briefing_leaks.py`` captures the real HTTP request and checks.

Optional: with no API key there is no client and everyone gets the rule-based briefing. Any
failure (network, rate limit, refusal, a cut-off answer) raises ``LLMUnavailableError`` and the
caller falls back to the rules.
"""

from __future__ import annotations

from typing import Any, Protocol

import anthropic
import httpx2

from app.core.config import Settings

MAX_TOKENS = 2000


class LLMUnavailableError(Exception):
    """The model could not give an answer; the reason is a short code, never the model's text."""


class BriefingLLM(Protocol):
    model: str

    def complete(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        """The model's answer, a JSON string matching ``schema``. Raises ``LLMUnavailableError``."""


class ClaudeBriefingLLM:
    def __init__(
        self, api_key: str, model: str, timeout: float, *, http_client: httpx2.Client | None = None
    ) -> None:
        self.model = model
        # One retry: the briefing is not worth a long wait, and the rule-based text is always there.
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=1, http_client=http_client
        )

    def complete(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                # A short summary of given facts: no extended thinking needed, low effort.
                thinking={"type": "disabled"},
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIError as exc:  # connection, timeout, rate limit, any status error
            raise LLMUnavailableError(type(exc).__name__) from exc
        if response.stop_reason == "refusal":
            raise LLMUnavailableError("refusal")
        if response.stop_reason == "max_tokens":
            raise LLMUnavailableError("truncated")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if not text:
            raise LLMUnavailableError("empty")
        return text


def from_settings(settings: Settings) -> ClaudeBriefingLLM | None:
    """The model client, or None when no API key is set (then the briefing is rule-based)."""
    if settings.anthropic_api_key is None:
        return None
    key = settings.anthropic_api_key.get_secret_value().strip()
    if not key:
        return None
    return ClaudeBriefingLLM(key, settings.briefing_model, settings.briefing_timeout_seconds)
