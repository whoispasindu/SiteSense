from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.errors import BusinessRuleError, ForbiddenError


class _Credentials(BaseModel):
    email: str
    password: str = Field(min_length=12)


def _add_probe_routes(app: FastAPI) -> None:
    @app.post("/probe/validate")
    def validate(body: _Credentials) -> dict[str, str]:
        return {"email": body.email}

    @app.get("/probe/forbidden")
    def forbidden() -> None:
        raise ForbiddenError()

    @app.get("/probe/rule")
    def rule() -> None:
        raise BusinessRuleError("Quantity exceeds the BOQ allowance.", details=[{"rule": "BR-02"}])

    @app.get("/probe/crash")
    def crash() -> None:
        raise RuntimeError("db password is hunter2 at /srv/secret/config.py line 42")


def _assert_envelope(body: dict[str, object], code: str) -> dict[str, object]:
    assert set(body) == {"error"}
    error = body["error"]
    assert isinstance(error, dict)
    assert set(error) == {"code", "message", "request_id", "details"}
    assert error["code"] == code
    assert isinstance(error["request_id"], str)
    assert error["request_id"]
    return error


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    _assert_envelope(response.json(), "not_found")


def test_wrong_method_uses_error_envelope(client: TestClient) -> None:
    response = client.delete("/api/v1/health")

    assert response.status_code == 405
    _assert_envelope(response.json(), "method_not_allowed")


def test_validation_errors_never_echo_submitted_values(app: FastAPI, client: TestClient) -> None:
    _add_probe_routes(app)

    response = client.post("/probe/validate", json={"email": "a@b.lk", "password": "tiny-pw"})

    assert response.status_code == 422
    error = _assert_envelope(response.json(), "validation_error")
    assert error["details"] == [
        {
            "field": "password",
            "message": "String should have at least 12 characters",
            "type": "string_too_short",
        }
    ]
    assert "tiny-pw" not in response.text


def test_app_errors_map_to_their_status_and_code(app: FastAPI, client: TestClient) -> None:
    _add_probe_routes(app)

    forbidden = client.get("/probe/forbidden")
    rule = client.get("/probe/rule")

    assert forbidden.status_code == 403
    _assert_envelope(forbidden.json(), "forbidden")
    assert rule.status_code == 422
    error = _assert_envelope(rule.json(), "business_rule_violation")
    assert error["message"] == "Quantity exceeds the BOQ allowance."
    assert error["details"] == [{"rule": "BR-02"}]


def test_unhandled_exception_returns_generic_500_with_headers(app: FastAPI, client: TestClient) -> None:
    _add_probe_routes(app)

    response = client.get("/probe/crash")

    assert response.status_code == 500
    error = _assert_envelope(response.json(), "server_error")
    assert error["message"] == "Something went wrong on our side."
    for leaked in ("hunter2", "Traceback", "RuntimeError", "config.py"):
        assert leaked not in response.text
    # The request ID returned to the user matches the header, so support can find the log line.
    assert response.headers["X-Request-ID"] == error["request_id"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
