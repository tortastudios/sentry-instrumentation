"""HTTP observability middleware — the Starlette/FastAPI reference.

Drop-in at `yourapp/middleware/observability.py`. Emits per-request
Sentry metrics (count, duration, conditional failure count) tagged
with method, route-name, HTTP status class (via `status_code_class()`),
and client type (from `request.state.auth` populated by the auth
dependency).

Consumers get full HTTP-route coverage by adding the middleware to
the app — never hand-roll these emissions in route handlers.

    app.add_middleware(ObservabilityMiddleware)

> Framework note: this reference uses `starlette.middleware.base`.
> The same triad applies in every HTTP framework — Django middleware,
> Flask `before_request`/`after_request`, Express/Koa middleware,
> Rails `ActionDispatch` middleware, Phoenix plugs. Preserve the
> triad; swap only the framework glue.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from yourapp.observability import emit_counter, emit_latency
from yourapp.shared.metric_tags import status_code_class
from yourapp.shared.metrics import MetricDef

logger = logging.getLogger(__name__)

# ---- Metric definitions ----------------------------------------------------

# Three metrics — count, duration, conditional failure count. The
# triad is the required emission set for the HTTP-route surface per
# the coverage table in `references/surface-patterns.md`.

API_REQUEST_COUNT = MetricDef.counter(
    "api.request.count",
    purpose="outcome",
    owner="platform",
    means=(
        "HTTP request observed by the middleware. Divide "
        "api.request.failure.count / api.request.count per (route, method) "
        "for the per-route failure rate."
    ),
    tags={
        "method": frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}),
        "route": "route_name",        # validated via `_route_name_for_tagging`
        "status_class": "status_code_class",
        "client_type": frozenset({"user", "service", "anonymous"}),
    },
    emit_frequency="per_request",
    max_rate_hz=1000.0,
)

API_REQUEST_DURATION = MetricDef.latency(
    "api.request.duration",
    owner="platform",
    means="Wall-clock duration of an HTTP request, measured around call_next.",
    tags={
        "method": frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}),
        "route": "route_name",
        "status_class": "status_code_class",
        "client_type": frozenset({"user", "service", "anonymous"}),
    },
    emit_frequency="per_request",
    sampling_rate=1.0,
    max_rate_hz=1000.0,
)

API_REQUEST_FAILURES = MetricDef.failure_counter(
    "api.request.failure.count",
    owner="platform",
    means=(
        "Failed HTTP requests — either 4xx/5xx response or unhandled "
        "exception. Tagged by the failure class produced by classify()."
    ),
    tags={
        "method": frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}),
        "route": "route_name",
        "status_class": "status_code_class",
    },
    emit_frequency="per_request",
    max_rate_hz=1000.0,
)


# ---- Middleware ------------------------------------------------------------


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Per-request emission to Sentry Metrics.

    Sentry tags are low-cardinality: method, route (from Starlette's
    matched route name), status-code class, client_type.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        started = time.monotonic()
        try:
            response: Response = await call_next(request)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            logger.exception("Unhandled exception in request")
            self._record(
                request=request,
                status_code=500,
                elapsed_ms=elapsed_ms,
                exception=exc,
            )
            raise
        elapsed_ms = (time.monotonic() - started) * 1000.0
        self._record(
            request=request,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            exception=None,
        )
        return response

    def _record(
        self,
        *,
        request: Request,
        status_code: int,
        elapsed_ms: float,
        exception: BaseException | None,
    ) -> None:
        tags = {
            "method": request.method,
            "route": _route_name_for_tagging(request),
            "status_class": status_code_class(status_code),
            "client_type": _client_type(request),
        }
        emit_counter(API_REQUEST_COUNT, tags=tags)
        emit_latency(API_REQUEST_DURATION, duration_ms=elapsed_ms, tags=tags)

        if status_code >= 400 or exception is not None:
            # Drop client_type from the failure counter — not in its
            # allowed_tags (status_class carries the useful signal).
            failure_tags = {
                "method": tags["method"],
                "route": tags["route"],
                "status_class": tags["status_class"],
            }
            from yourapp.shared.failure_taxonomy import FailureClass, classify

            failure = classify(exception) if exception else _failure_from_status(status_code)
            from yourapp.observability import emit_failure

            emit_failure(API_REQUEST_FAILURES, failure=failure, tags=failure_tags)


def _route_name_for_tagging(request: Request) -> str:
    """Return the matched route's `name`, never the raw URL.

    Starlette populates `request.scope["route"]` with the matched
    `APIRoute`/`Route`. Its `.name` is a stable string the app owns;
    the URL path carries path params (PII risk, cardinality blowup).
    Unmatched routes (middleware firing on 404) fall back to a
    bucketed label.
    """

    route = request.scope.get("route")
    name = getattr(route, "name", None)
    if name:
        return str(name)
    return "unmatched"


def _client_type(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth is None:
        return "anonymous"
    return getattr(auth, "client_type", "user")


def _failure_from_status(status_code: int) -> "FailureClass":
    """Best-effort FailureClass from the HTTP status code."""

    from yourapp.shared.failure_taxonomy import FailureClass

    if status_code == 401:
        return FailureClass.AUTH_FAILURE
    if status_code == 403:
        return FailureClass.AUTH_FAILURE
    if status_code == 404:
        return FailureClass.VALIDATION_FAILURE
    if status_code == 408:
        return FailureClass.TIMEOUT
    if status_code == 429:
        return FailureClass.RATE_LIMITED
    if 500 <= status_code < 600:
        return FailureClass.INTERNAL_ERROR
    return FailureClass.UNKNOWN
