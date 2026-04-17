"""Bounded failure taxonomy for system-behavior instrumentation.

Drop-in at `yourapp/shared/failure_taxonomy.py`. Every failure-counter
metric tags with one value from `FailureClass`. Raw exception strings
are forbidden as tag values: cardinality explodes, PII leaks through,
and downstream alert rules can't match on them. Call sites bucket
their raw exception through `classify()` before emitting.

The classifier is intentionally small. Domain modules register their
own exception types via `register()` at module scope so this module
stays free of upward dependencies on `services/`.

The `UNKNOWN` bucket is deliberate — its rate is its own SLI. A
rising `UNKNOWN` rate means either a new exception class is being
raised without a `register()` call, or an external dependency is
failing in a shape the classifier hasn't seen.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum


class FailureClass(StrEnum):
    """Closed taxonomy of system-behavior failure buckets."""

    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DEPENDENCY_FAILURE = "dependency_failure"
    VALIDATION_FAILURE = "validation_failure"
    AUTH_FAILURE = "auth_failure"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    INTERNAL_ERROR = "internal_error"
    UNKNOWN = "unknown"


_REGISTERED: dict[type[BaseException], FailureClass] = {}


def register(exc_cls: type[BaseException], failure: FailureClass) -> None:
    """Bind an exception class to a taxonomy value.

    Call at module scope next to the exception's definition so the
    mapping travels with the exception. Re-registration overwrites
    the prior mapping.
    """

    _REGISTERED[exc_cls] = failure


def classify(exc: BaseException) -> FailureClass:
    """Return the taxonomy value for `exc`, walking its MRO.

    Registered exceptions win over stdlib fallbacks. Exceptions that
    aren't registered and aren't one of the known stdlib shapes fall
    through to `UNKNOWN`.

    `CancelledError` inherits from `BaseException` (not `Exception`)
    since Python 3.8 — the explicit isinstance check catches it even
    when re-raised through `except Exception`.
    """

    for cls in type(exc).__mro__:
        registered = _REGISTERED.get(cls)
        if registered is not None:
            return registered
    if isinstance(exc, asyncio.CancelledError):
        return FailureClass.CANCELLED
    if isinstance(exc, TimeoutError):
        return FailureClass.TIMEOUT
    if isinstance(exc, ValueError):
        return FailureClass.VALIDATION_FAILURE
    return FailureClass.UNKNOWN


# Example registrations for domain exception types — typically these
# live next to the exception classes themselves, not in this module.
# Shown here for illustration; delete when adapting.
#
# from yourapp.services.providers.myservice import (
#     MyServiceQuotaExhaustedError,
#     MyServiceUpstreamError,
#     MyServiceForbiddenError,
# )
# register(MyServiceQuotaExhaustedError, FailureClass.QUOTA_EXHAUSTED)
# register(MyServiceUpstreamError, FailureClass.DEPENDENCY_FAILURE)
# register(MyServiceForbiddenError, FailureClass.AUTH_FAILURE)


__all__ = ["FailureClass", "classify", "register"]
