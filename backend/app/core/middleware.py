"""
Request-ID + access-log middleware.

Each request gets a UUID exposed as `X-Request-ID`. The id is attached to the
log record for every line emitted while the request is in flight, making it
easy to correlate a single user action across multiple log entries.
"""
from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging_setup import get_logger

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
log = get_logger("app.access")


def current_request_id() -> str | None:
    return _request_id.get()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = _request_id.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            log.exception(
                "request failed",
                extra={
                    "request_id": rid,
                    "method": request.method,
                    "path": request.url.path,
                    "elapsed_ms": round(elapsed, 2),
                },
            )
            raise
        finally:
            _request_id.reset(token)

        elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = rid
        # Don't log /health every 10s — too chatty for the audit trail.
        if request.url.path != "/health":
            log.info(
                "request",
                extra={
                    "request_id": rid,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "elapsed_ms": round(elapsed, 2),
                },
            )
        return response
