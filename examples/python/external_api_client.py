"""Instrumented HTTP client base class — the drop-in pattern for external APIs.

Drop-in at `yourapp/services/providers/instrumented_http_client.py`.
Subclass per dependency; the base emits the required triad
(per-call duration + outcome counter tagged by `failure_class` +
rate-limit counter) so consumers never hand-roll emissions for an
API call.

Uses `httpx.AsyncClient`. To swap for `aiohttp` or `requests`, keep
the triad — change only the transport. In other languages, the same
pattern applies: wrap `axios`/`fetch` (TS), `http.RoundTripper` (Go),
`Faraday` middleware (Ruby), `HttpClient` handler (Java/Kotlin).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any, ClassVar

import httpx

from yourapp.observability import (
    emit_counter,
    emit_failure,
    emit_latency,
)
from yourapp.shared.failure_taxonomy import FailureClass, classify
from yourapp.shared.metric_tags import status_code_class
from yourapp.shared.metrics import MetricDef

logger = logging.getLogger(__name__)


# ---- Metric definitions ----------------------------------------------------

DEPENDENCY_CALL_COUNT = MetricDef.counter(
    "dependency.call.count",
    purpose="outcome",
    owner="platform",
    means="External dependency HTTP call observed by the instrumented client.",
    tags={
        "dep": "dep_name",          # subclass `.dep_name` class var
        "method": frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"}),
        "status_class": "status_code_class",
    },
    emit_frequency="per_event",
    max_rate_hz=500.0,
)

DEPENDENCY_CALL_DURATION = MetricDef.latency(
    "dependency.call.duration",
    owner="platform",
    means="Wall-clock duration of an outbound HTTP call, measured around `request()`.",
    tags={
        "dep": "dep_name",
        "method": frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"}),
        "status_class": "status_code_class",
    },
    emit_frequency="per_event",
    sampling_rate=1.0,
    max_rate_hz=500.0,
)

DEPENDENCY_CALL_FAILURES = MetricDef.failure_counter(
    "dependency.call.failure.count",
    owner="platform",
    means="Outbound HTTP call failed — tagged by FailureClass.classify(exc).",
    tags={
        "dep": "dep_name",
        "method": frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"}),
    },
    emit_frequency="per_event",
    max_rate_hz=500.0,
)


# ---- Base class ------------------------------------------------------------


class InstrumentedHttpClient:
    """Base class wrapping `httpx.AsyncClient` with the dependency triad.

    Subclass per dependency and set `dep_name` as a class variable.
    Override nothing else unless the dependency needs custom parsing —
    the emissions are automatic.

    Example:
        class ExternalApiClient(InstrumentedHttpClient):
            dep_name: ClassVar[str] = "external_api"

            async def fetch(self, value: str, *, kind: str) -> FetchResponse:
                response = await self.request("GET", "/resources", params={...})
                return FetchResponse.from_httpx(response)
    """

    dep_name: ClassVar[str] = "unknown"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """One HTTP call with the triad emitted around it."""

        started = time.monotonic()
        status_code: int | None = None
        exc: BaseException | None = None
        try:
            response = await self._client.request(
                method,
                url,
                params=dict(params) if params else None,
                json=json,
                headers=dict(headers) if headers else None,
                timeout=timeout,
            )
            status_code = response.status_code
        except BaseException as caught:
            exc = caught
            raise
        finally:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            status_class = (
                status_code_class(status_code) if status_code is not None else "other"
            )
            tags: dict[str, str] = {
                "dep": self.dep_name,
                "method": method.upper(),
                "status_class": status_class,
            }
            emit_counter(DEPENDENCY_CALL_COUNT, tags=tags)
            emit_latency(DEPENDENCY_CALL_DURATION, duration_ms=elapsed_ms, tags=tags)
            if exc is not None or (status_code is not None and status_code >= 400):
                failure = (
                    classify(exc)
                    if exc is not None
                    else _failure_from_status(status_code or 0)
                )
                emit_failure(
                    DEPENDENCY_CALL_FAILURES,
                    failure=failure,
                    tags={"dep": self.dep_name, "method": method.upper()},
                )

        return response


def _failure_from_status(status_code: int) -> FailureClass:
    if status_code == 401 or status_code == 403:
        return FailureClass.AUTH_FAILURE
    if status_code == 404:
        return FailureClass.VALIDATION_FAILURE
    if status_code == 408:
        return FailureClass.TIMEOUT
    if status_code == 429:
        return FailureClass.RATE_LIMITED
    if 500 <= status_code < 600:
        return FailureClass.DEPENDENCY_FAILURE
    return FailureClass.UNKNOWN


__all__ = [
    "DEPENDENCY_CALL_COUNT",
    "DEPENDENCY_CALL_DURATION",
    "DEPENDENCY_CALL_FAILURES",
    "InstrumentedHttpClient",
]
