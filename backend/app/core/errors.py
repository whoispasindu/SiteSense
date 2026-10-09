"""Central error handling: every error reaches the client in the same JSON shape.

    {"error": {"code": "not_found", "message": "Project not found", "details": ...}}

Stack traces are logged on the server and never sent to the client.
"""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """An expected error that should reach the client with a clear message.

    Services raise these (or a subclass) instead of returning error values.
    """

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code is not None:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=status_code, content={"error": body}, headers=headers)


def _code_for_status(status_code: int) -> str:
    """Turns an HTTP status into a short code, e.g. 404 -> "not_found"."""
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "http_error"


async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return error_response(
        exc.status_code,
        _code_for_status(exc.status_code),
        str(exc.detail),
        headers=exc.headers,
    )


async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # loc looks like ("body", "quantity"); keep the field path and drop the location prefix
    details = [
        {
            "field": ".".join(str(part) for part in error["loc"][1:]),
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    return error_response(422, "validation_error", "Some fields are invalid.", details)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
