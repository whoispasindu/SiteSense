import json
import logging

import pytest
import structlog

from app.core.logging import REDACTED, configure_logging, get_logger, redact_sensitive


def test_sensitive_top_level_keys_are_redacted() -> None:
    event = redact_sensitive(
        None,
        "info",
        {"event": "login", "email": "pm@site.lk", "password": "hunter2", "access_token": "eyJ..."},
    )

    assert event == {"event": "login", "email": "pm@site.lk", "password": REDACTED, "access_token": REDACTED}


def test_sensitive_nested_keys_are_redacted() -> None:
    event = redact_sensitive(
        None,
        "info",
        {
            "event": "call",
            "headers": {"Authorization": "Bearer x", "Accept": "json"},
            "items": [{"api_key": "k"}],
        },
    )

    assert event["headers"] == {"Authorization": REDACTED, "Accept": "json"}
    assert event["items"] == [{"api_key": REDACTED}]


def test_json_logs_are_valid_json_and_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.reset_defaults()
    configure_logging("INFO", json_logs=True)

    get_logger("test").info("signed_in", user="u1", password="hunter2")
    logging.getLogger().handlers[0].flush()

    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "signed_in"
    assert record["password"] == REDACTED
    assert record["level"] == "info"
    assert "hunter2" not in line
