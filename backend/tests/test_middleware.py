from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def test_every_response_carries_security_headers(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in response.headers  # only in production


def test_error_responses_also_carry_security_headers(client: TestClient) -> None:
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.headers["X-Frame-Options"] == "DENY"


def test_hsts_is_sent_in_production() -> None:
    settings = make_settings(
        environment="production",
        cors_origins=["https://app.sitesense.example"],
        database_url="postgresql+psycopg://app:s3cure-pw@db:5432/sitesense",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")

    assert response.headers["Strict-Transport-Security"].startswith("max-age=")


def test_request_id_is_generated_when_missing(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert len(response.headers["X-Request-ID"]) == 32


def test_safe_incoming_request_id_is_kept(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc_123.x"})

    assert response.headers["X-Request-ID"] == "trace-abc_123.x"


@pytest.mark.parametrize(
    "hostile", ["short", "a" * 65, "abc\r\nSet-Cookie: x=1", "<script>alert(1)</script>"]
)
def test_unsafe_incoming_request_id_is_replaced(client: TestClient, hostile: str) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": hostile})

    assert response.headers["X-Request-ID"] != hostile
    assert len(response.headers["X-Request-ID"]) == 32


def _echo_app() -> FastAPI:
    app = create_app(make_settings(max_request_body_bytes=2048))

    @app.post("/probe/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    return app


def test_body_within_limit_is_accepted() -> None:
    with TestClient(_echo_app()) as client:
        response = client.post("/probe/echo", content=b"x" * 2048)

    assert response.status_code == 200
    assert response.json() == {"size": 2048}


def test_declared_oversized_body_is_rejected_before_reading() -> None:
    with TestClient(_echo_app()) as client:
        response = client.post("/probe/echo", content=b"x" * 4096)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_streamed_oversized_body_without_length_is_rejected() -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(4):
            yield b"x" * 1024

    with TestClient(_echo_app()) as client:
        response = client.post("/probe/echo", content=chunks())

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_malformed_content_length_is_rejected() -> None:
    with TestClient(_echo_app()) as client:
        response = client.post("/probe/echo", content=b"{}", headers={"Content-Length": "abc"})

    assert response.status_code == 413


def test_unknown_host_header_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Host": "evil.example"})

    assert response.status_code == 400


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert response.headers["Access-Control-Allow-Credentials"] == "true"


def test_cors_ignores_unknown_origin(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})

    assert "Access-Control-Allow-Origin" not in response.headers
