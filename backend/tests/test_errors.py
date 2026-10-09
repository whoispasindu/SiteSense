from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import ConflictError, NotFoundError, register_error_handlers
from app.core.middleware import request_context_middleware


def make_app() -> FastAPI:
    """A small app wired like app.main, with routes that fail in each possible way."""
    app = FastAPI()
    app.middleware("http")(request_context_middleware)
    register_error_handlers(app)

    @app.get("/not-found")
    def not_found():
        raise NotFoundError("Project not found")

    @app.get("/conflict")
    def conflict():
        raise ConflictError("A report already exists for this date", code="duplicate_report")

    @app.get("/items/{item_id}")
    def get_item(item_id: int):
        return {"id": item_id}

    @app.get("/crash")
    def crash():
        raise RuntimeError("secret internal detail")

    return app


client = TestClient(make_app())


def test_app_error_uses_standard_shape():
    response = client.get("/not-found")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Project not found"}}


def test_app_error_can_override_code():
    response = client.get("/conflict")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_report"


def test_unknown_route_uses_standard_shape():
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_validation_error_lists_fields():
    response = client.get("/items/not-a-number")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "item_id"


def test_unhandled_error_hides_internal_details():
    response = client.get("/crash")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
