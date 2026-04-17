# Reusable surface patterns

Canonical instrumentation ships as **drop-in code**, not as "write
these emissions at each site". Each surface in the service has one
entry in the registry (the `MetricDef` set) and one reusable pattern
(middleware, decorator, context manager, base class) that bakes in
the emission sites. Consumers write domain logic; instrumentation is
not copy-pasted per site.

## Surface coverage table

| Surface | Pattern | Required emissions (baked in) |
|---|---|---|
| HTTP route | `ObservabilityMiddleware` | request count, request duration, failure count tagged by status class |
| External API client | `InstrumentedHttpClient` subclass | call count, call duration, failure count tagged by `failure_class`, rate-limit counter |
| Workflow step | `@instrumented_step(stage_name)` decorator | duration (always), failure counter tagged by `failure_class` |
| Queue worker | `instrumented_worker(queue_name)` | enqueue count, dequeue count, terminal outcome, in-flight gauge |
| Retry loop | `retry_with_instrumentation(metric, max_attempts)` | attempt count tagged by `attempt_bucket`, terminal outcome |
| Fallback path | `record_fallback(metric, reason=...)` | fallback count tagged with taxonomy value |

Using the pattern is always less code than hand-rolling the
emissions. That's the "correct path is the easiest path" guarantee.

## 1. HTTP route — `ObservabilityMiddleware`

ASGI middleware. Timed at `call_next` enter/exit, tagged with method,
route-name (from the matched `starlette.routing.Route.name`), HTTP
status class (via `status_code_class()`), and client type (auth
resolved from `request.state.auth`).

Wiring: add once to the app, emissions land for every route. See
`examples/python/http_middleware.py` for a complete drop-in module.

```python
app.add_middleware(ObservabilityMiddleware)
```

## 2. External API client — `InstrumentedHttpClient`

Base class wrapping `httpx.AsyncClient`. Subclass per dependency,
override the request methods with the upstream API's semantics; the
base emits per-call duration + outcome (tagged with `failure_class`
from `classify(exc)`) + rate-limit counter.

```python
class ExternalApiClient(InstrumentedHttpClient):
    dep_name = "external_api"

    async def fetch(self, value: str, *, kind: str) -> FetchResponse:
        response = await self.request("GET", "/resources", params={...})
        return FetchResponse.from_httpx(response)
```

> Language note: the pattern (base class with pre/post-call emission
> hooks) translates directly — in TypeScript, use an `axios`/`fetch`
> wrapper that records the triad around the call. In Go, wrap
> `http.RoundTripper`.

Consumers never touch `emit_*` for an API call. The base class
handles the triad. See `examples/python/external_api_client.py`.

## 3. Workflow step — `@instrumented_step(stage_name)`

Decorator applied to a workflow task (Hatchet, Celery, Temporal,
Sidekiq, Inngest, BullMQ, or equivalent). Sits inside the workflow
engine's own decorator so the engine sees the wrapped function:

```python
@workflow.task(retries=2, execution_timeout="5m")
@instrumented_step(stages.INGEST)
async def ingest(input, ctx):
    ...
```

Emits `stage.duration` (always) + `stage.failure_count` tagged by
`failure_class` (on exception, via `classify()`). Exception is
re-raised after emission — the decorator is observational, not
swallowing. See `examples/python/workflow_decorator.py`.

## 4. Retry loop — `retry_with_instrumentation`

Async iterator + context manager that wraps a retry loop:

```python
async for attempt in retry_with_instrumentation(
    metric=EXTERNAL_API_RETRY,
    max_attempts=3,
    tags={"endpoint": "list"},
):
    async with attempt:
        return await client.fetch(...)
```

Emits one counter per loop exit (tagged with `attempt_bucket` of the
attempt index at termination + outcome from the terminal state).
Aggregates via `AggregatingCounter` internally so the per-iteration
path is zero emissions. See `examples/python/retry_loop.py`.

## 5. Fallback path — `record_fallback`

Single-call helper:

```python
record_fallback(PRIMARY_SIGNAL_FALLBACK, reason="primary_empty")
```

- `reason` is validated against the metric's
  `tag_constraints["reason"]` set.
- The helper is the *only* approved way to emit a fallback counter;
  the CI gate rejects raw `emit_counter(..., tags={"reason": ...})`
  against a metric that was registered as a fallback metric.
- See `examples/python/fallback_path.py`.

## 6. Queue worker — `instrumented_worker`

Wraps the queue consumer loop: emits `enqueue.count` on receive,
`dequeue.count` on ack, `outcome.count` tagged with `failure_class`
on terminal, and maintains an in-flight gauge. Not included as a
standalone example module — typical integrations (Hatchet, Celery,
RQ, Sidekiq, BullMQ, SQS, Redis streams) look slightly different.
Extend `InstrumentedHttpClient`'s triad pattern to the consumer
loop.

## Adding a new surface pattern

A new pattern earns its place when you've hand-rolled the same
emission triad three times across the codebase. Propose it in the PR
that adds the third copy:

1. Name it `Instrumented<Noun>` (base class) or `@instrumented_<noun>`
   (decorator) for consistency.
2. Declare its `MetricDef` set in one place — tests can assert on
   existence.
3. Write a drop-in example module parallel to the ones in
   `examples/`.
4. Update this file + the coverage table.
