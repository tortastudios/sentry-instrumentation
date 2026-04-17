# Emission boundaries — where metrics belong

Metrics are emitted at **choke points** — the small number of places
in a service where something meaningful happened from an operational
standpoint. Scatter emissions across every function call and you get
both noise (every object mutation as an "event") and coverage gaps
(the interesting boundary was silent).

## Belongs

Emit at:

- **Request ingress / egress.** One count + one distribution per
  HTTP request, tagged with method / route / status class. Handled by
  `ObservabilityMiddleware` — don't hand-roll in route handlers.
- **Workflow step boundaries.** One duration + one conditional
  failure counter per workflow step (Hatchet task, Celery task,
  Temporal activity, Sidekiq job, Inngest function, BullMQ worker).
  Handled by `@instrumented_step` — don't hand-roll in step bodies.
- **External dependency calls.** One duration + one outcome counter
  per call to any external dependency (third-party APIs, databases,
  caches, LLM providers, message brokers). Handled by
  `InstrumentedHttpClient` subclasses (or your language's equivalent
  wrapper pattern).
- **Retry points.** Attempt counter (tagged via `attempt_bucket`) +
  terminal outcome at loop exit. Handled by
  `retry_with_instrumentation`.
- **Queue enqueue / dequeue.** Counters + in-flight gauge. Handled by
  `instrumented_worker` wrapping the queue consumer.
- **Degradation / fallback paths.** Counter with taxonomy-valued
  reason. Handled by `record_fallback`.
- **Failure classification sites.** The catch block that maps a raw
  exception to a `FailureClass` via `classify()` and emits via
  `emit_failure`.

## Does not belong

Do not emit at:

- **Inside tight loops** (per-iteration emissions) — use
  `AggregatingCounter` / `DurationAccumulator`.
- **Every object mutation.** A metric that fires on every attribute
  set isn't a metric, it's a stack trace.
- **Low-level helpers that aren't shared choke points.** If only one
  caller invokes the helper, emit at the caller instead. If many do,
  the helper may be a surface worth its own `InstrumentedX` wrapper.
- **Places without stable enumerated dimensions.** If you can't write
  the `tag_constraints` without listing user inputs, the site isn't
  ready for a metric.
- **Inside a try/except that's just translating exceptions.** Let the
  outer boundary (the workflow step, the middleware) classify and
  emit.

## Coverage map by surface

| Surface | Canonical pattern | Emissions baked in |
|---|---|---|
| HTTP route | `ObservabilityMiddleware` (or framework equivalent) | request count, request duration, failure count (tagged by status class) |
| External dependency client | `InstrumentedHttpClient` subclass (or language equivalent) | call count, call duration, failure count (tagged by `failure_class`), rate-limit counter |
| Workflow step | `@instrumented_step(stage_name)` | duration (always), failure counter (on exception, tagged by `failure_class`) |
| Queue worker | `instrumented_worker(queue_name)` | enqueue count, dequeue count, terminal outcome, in-flight gauge |
| Retry loop | `retry_with_instrumentation(metric, max_attempts)` | attempt count tagged by `attempt_bucket`, terminal outcome |
| Fallback path | `record_fallback(metric, reason=...)` | fallback count tagged with taxonomy value |

If you're tempted to hand-roll an emission for one of these surfaces,
check whether the canonical pattern already covers it first. Using
the pattern is always less code than hand-rolling.

## Deciding when a surface is new enough to need its own pattern

If you find yourself hand-rolling the same three emissions in three
files with slight copy-paste drift, that's a signal a new surface
pattern is due. Propose it in the PR that adds the third copy.
Surface patterns are cheap when the emission triad is stable; adding
one later to unify drifted copies is painful.
