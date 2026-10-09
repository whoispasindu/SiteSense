import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response

from app.core.errors import error_response

logger = logging.getLogger("sitesense.requests")


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Gives every request an ID, logs it with its duration, and turns crashes into clean 500s.

    Expected errors (AppError, HTTPException, validation) are already turned into responses by
    the handlers in errors.py, so anything caught here is a bug and is logged with its traceback.
    """
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.request_id = request_id
    log_fields = {"request_id": request_id, "method": request.method, "path": request.url.path}
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error", extra=log_fields)
        response = error_response(
            500, "internal_error", "Something went wrong on our side. Please try again later."
        )

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "Request handled",
        extra={**log_fields, "status_code": response.status_code, "duration_ms": duration_ms},
    )
    response.headers["X-Request-ID"] = request_id
    return response
