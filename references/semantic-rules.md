# Kind semantic rules

Hard contracts per `kind`. The emission helper API enforces these;
the CI gate rejects violations at merge time.

> Language note: helper names below (`emit_counter`,
> `AggregatingCounter`, `time_latency`, etc.) are the canonical Python
> reference. Ports to other languages keep the same shapes under
> idiomatic names — a TS port might expose `emitCounter()` /
> `AggregatingCounter` / `timeLatency()` with the same contracts.

## `counter`

- **Monotonic event occurrences.** Each emission adds to a running
  total. Values are typically `1.0`; values > 1 mean "batch of N
  events".
- Never a state snapshot. Never a current value. Never a rate.
- Unit is `"count"` (for `outcome` counters) or a consumable-resource
  unit like `"units"`, `"tokens"`, `"byte"` (for `resource` counters).
- Use `emit_counter(metric, tags=..., value=1.0)` — or, inside a
  loop, wrap in `AggregatingCounter`.

## `gauge`

- **Current measured state.** Each emission replaces (or is sampled
  as) the current value.
- **No percentiles.** Sentry aggregates gauges with `min`, `max`,
  `avg` (plus rates); only distributions give p50/p75/p90/p95/p99.
  Sentry's rule of thumb: "Gauges are more space-efficient; pick them
  when you do not need percentiles"
  ([Python docs](https://docs.sentry.io/platforms/python/metrics/)).
- Never cumulative. Never a rate. If "the number only ever goes up",
  it's a counter.
- Must have a unit — `"items"`, `"byte"`, `"second"`, etc.
- Typical `emit_frequency="periodic"`; sampled on a schedule or at a
  meaningful lifecycle boundary (queue drained, pool grown).
- Use `emit_gauge(metric, tags=..., value=...)`.

## `distribution`

- **A population of measured values** — latency, size, duration.
  Sentry computes `p50`, `p75`, `p90`, `p95`, `p99`, `avg`, `sum`,
  `min`, `max` and `count` over the stored events.
- Never a count in disguise. A distribution of `value=1.0` for every
  event is an abuse; use a counter.
- **Unit is mandatory.** Duration metrics are always measured in
  milliseconds and sent with unit `"millisecond"` (or the legacy
  `"ms"` for metrics registered earlier — see `signal-model.md`).
- Duration metrics must go through `MetricDef.latency(...)` (which
  fixes `kind="distribution"`, `purpose="latency"`). The
  start→stop boundary lives in `operational_meaning`. Different
  boundary = different metric.
- Use `emit_latency(metric, duration_ms=..., tags=...)` or the
  `time_latency(metric, tags=...)` context manager. Inside loops, use
  `DurationAccumulator`.

## Failure counters

A special case of `counter`:

- Built only via `MetricDef.failure_counter(...)`. The constructor
  pins `kind="counter"`, `unit="count"`, `purpose="outcome"`, and
  injects `failure_class` into `allowed_tags` with the full
  `FailureClass` taxonomy.
- Emitted only via
  `emit_failure(metric, failure=classify(exc), tags=...)`. Do not
  pass `str(exc)` or `type(exc).__name__` as a tag — downstream
  alerts can't match on it and group-bys become unreadable.
- The `UNKNOWN` bucket is expected. Its rate is its own SLI. Do not
  suppress it.

## Why these rules are enforced, not advised

Mixing kinds silently breaks downstream dashboards. A counter graphed
as if it were a gauge looks like a slow-rising line; a gauge graphed
as if it were a counter looks like a monotonic ramp. A "distribution"
that only ever records `1.0` produces nonsense percentiles.

The helper API refuses a wrong `kind` in pytest + non-production by
raising `InstrumentationContractError`; in production it drops the
emission and increments `instrumentation.violation.count` so the
regression shows up on a dashboard rather than taking the process
down.
