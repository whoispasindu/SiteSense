"""One error envelope for every failure the API returns.

Every error response has the shape::

    {"error": {"code": "not_found", "message": "...", "request_id": "...", "details": [...]}}

Stack traces and raw exception messages never reach the client; they go to the server log,
correlated by ``request_id``.
"""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.core.request_context import get_request_id

log = get_logger(__name__)


class AppError(Exception):
    """Base class for errors that are safe to show to the API caller."""

    status_code: int = HTTPStatus.BAD_REQUEST
    code: str = "bad_request"
    message: str = "The request could not be processed."
    headers: dict[str, str] | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = list(details or [])
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"
    message = "The requested resource was not found."


class UnauthorizedError(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "unauthorized"
    message = "Authentication is required."
    headers = {"WWW-Authenticate": "Bearer"}  # noqa: RUF012 - read-only class default


class ForbiddenError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = "forbidden"
    message = "You do not have permission to perform this action."


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    code = "conflict"
    message = "The request conflicts with the current state of the resource."


class BusinessRuleError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "business_rule_violation"
    message = "The request breaks a business rule."


class PayloadTooLargeError(AppError):
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    code = "payload_too_large"
    message = "The request body is too large."


_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
}


def error_body(code: str, message: str, details: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": get_request_id(),
            "details": list(details or []),
        }
    }


def _safe_validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Keep location, message and type; drop ``input`` and ``ctx``.

    Pydantic echoes the submitted value back by default, which would reflect passwords
    and other sensitive input into responses (and into any logs that capture them).
    """
    details = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ()) if part != "body"]
        details.append({"field": ".".join(loc) or None, "message": err.get("msg"), "type": err.get("type")})
    return details


async def _app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        error_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=exc.headers
    )


async def _validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        error_body("validation_error", "Some fields are missing or invalid.", _safe_validation_details(exc)),
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


async def _http_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    status = exc.status_code
    code = _STATUS_CODES.get(status, "server_error" if status >= 500 else "http_error")
    # Framework messages ("Not Found", "Method Not Allowed") are safe; anything else is replaced
    # with the generic phrase so internal detail strings cannot leak.
    message = HTTPStatus(status).phrase if status >= 500 else str(exc.detail)
    return JSONResponse(error_body(code, message), status_code=status, headers=getattr(exc, "headers", None))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    # Unhandled exceptions are caught by RequestContextMiddleware, which returns a generic 500
    # with the same envelope and logs the traceback.
