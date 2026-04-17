# Failure taxonomy

Every failure counter tags with one value from a closed, bounded set
— the `FailureClass`. Raw exception strings as tag values are
forbidden: cardinality blows up, PII leaks through, downstream alert
rules can't match on them.

## `FailureClass`

```python
class FailureClass(StrEnum):
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DEPENDENCY_FAILURE = "dependency_failure"
    VALIDATION_FAILURE = "validation_failure"
    AUTH_FAILURE = "auth_failure"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    INTERNAL_ERROR = "internal_error"
    UNKNOWN = "unknown"
```

### Bucket meanings

| Value | Meaning |
|---|---|
| `timeout` | Operation exceeded a time budget. Our side or dependency side — stdlib `TimeoutError`, `asyncio.TimeoutError`, or dependency-specific timeout classes. |
| `cancelled` | `asyncio.CancelledError` — request/task cancellation propagated (client disconnect, scheduler preempt). Separate from timeout so alerts don't conflate the two. |
| `dependency_failure` | External dependency returned an error we couldn't recover from (5xx after retries, connection refused). |
| `validation_failure` | Input failed validation before reaching the dependency — `ValueError`, `pydantic.ValidationError`, domain invariant errors. |
| `auth_failure` | Credentials missing, invalid, expired, or forbidden (403 for permission reasons — not quota). |
| `rate_limited` | Dependency returned 429 or equivalent. Distinct from quota exhaustion (which is a daily/monthly budget, not a per-second cap). |
| `quota_exhausted` | Daily / monthly budget consumed — e.g., third-party API daily quota exceeded, LLM monthly cap. |
| `internal_error` | We know it's our bug: assertion failure, invariant violation, unexpected `None`. |
| `unknown` | Classifier had no mapping. Its rate is its own SLI. |

### Why `UNKNOWN` is deliberate

A rising `UNKNOWN` rate means either:

1. A new exception class is being raised that nobody `register()`-ed,
   or
2. A dependency is failing in a shape the classifier hasn't seen.

Either is actionable. Suppressing `UNKNOWN` to "clean up" the
taxonomy hides the signal.

## `classify(exc: BaseException) -> FailureClass`

The classifier walks the exception's MRO looking for a registered
class, then falls through to stdlib isinstance checks, then returns
`UNKNOWN`.

```python
for cls in type(exc).__mro__:
    if cls in _REGISTERED:
        return _REGISTERED[cls]

if isinstance(exc, asyncio.CancelledError):
    return FailureClass.CANCELLED
if isinstance(exc, TimeoutError):
    return FailureClass.TIMEOUT
if isinstance(exc, ValueError):
    return FailureClass.VALIDATION_FAILURE
return FailureClass.UNKNOWN
```

`asyncio.CancelledError` inherits from `BaseException` (not
`Exception`) since Python 3.8 — the explicit isinstance check catches
it even when re-raised through an `except Exception` block.

## Registering project exceptions

Each domain module binds its exception classes at import time:

```python
# in yourapp/services/providers/external_service.py
from yourapp.shared.failure_taxonomy import FailureClass, register

class MyServiceQuotaExhaustedError(Exception): ...
class MyServiceUpstreamError(Exception): ...
class MyServiceForbiddenError(Exception): ...

register(MyServiceQuotaExhaustedError, FailureClass.QUOTA_EXHAUSTED)
register(MyServiceUpstreamError, FailureClass.DEPENDENCY_FAILURE)
register(MyServiceForbiddenError, FailureClass.AUTH_FAILURE)
```

This pattern keeps the classifier free of upward dependencies on
`services/` — the registry is populated when each domain module
imports.

> Language note: the registration pattern generalizes — in TypeScript,
> map error constructors through a WeakMap<ErrorCtor, FailureClass>;
> in Go, use a `switch err.(type)` inside a package-level classifier.
> The shape "closed set of failure buckets + pluggable per-module
> registrations" is portable.

## Emitting a failure counter

Always via `emit_failure`, which reads the `failure_class` tag from
the constructor-guaranteed constraint set:

```python
from yourapp.observability import emit_failure
from yourapp.shared.failure_taxonomy import classify

try:
    await client.fetch(...)
except Exception as exc:
    emit_failure(
        EXTERNAL_API_FAILURES,
        failure=classify(exc),
        tags={"endpoint": "list"},
    )
    raise
```

The helper validates that `failure.value` is in the metric's
`tag_constraints["failure_class"]` set. Forgetting the
`failure=` argument is a `TypeError`. Passing a raw string like
`"quota"` is a contract error caught in pytest.

## Evolving the taxonomy

Adding a new `FailureClass` value is a deliberate, whole-project
decision:

1. It must cover a failure mode that isn't semantically captured by
   any existing bucket (`rate_limited` and `quota_exhausted` are the
   model for a tight distinction).
2. Update this file, the example `failure_taxonomy.py`, and every
   failure-counter `MetricDef` that could legitimately emit the new
   value.
3. Update downstream dashboards and alert rules to recognize the new
   value.

Removing a value is even more deliberate — dashboards that filter on
the old value go empty silently.
