from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # The database may or may not be running where the tests run; both answers are valid here
    assert body["database"] in ("ok", "unavailable")


def test_every_response_has_a_request_id():
    response = client.get("/health")

    assert response.headers["X-Request-ID"]


def test_incoming_request_id_is_kept():
    response = client.get("/health", headers={"X-Request-ID": "abc123"})

    assert response.headers["X-Request-ID"] == "abc123"
