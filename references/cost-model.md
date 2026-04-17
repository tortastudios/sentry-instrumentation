# Cost model

Every `MetricDef` declares its cost shape — `emit_frequency`,
`sampling_rate`, `max_rate_hz`, `loop_policy`. The helper API and CI
gate enforce those declarations so a single hot-path site can't blow
up the Sentry bill.

## Emission frequency guidance

The `emit_frequency` field tells the reader (and the rate limiter)
roughly how often a metric is expected to fire. Pick the closest
class:

| Frequency | Approximate cap | Typical use |
|---|---|---|
| `per_request` | hundreds/s | HTTP middleware |
| `per_step` | tens/s | workflow step boundaries |
| `per_event` | hundreds/s | external API calls, cache lookups |
| `periodic` | ≤ 1/s | gauges sampled on a schedule |

If an emission site fires faster than the class cap, either change
the class or sample. CI flags emission sites whose containing
function is clearly hotter than the declared class (best-effort).

## Sampling for distributions

- Distributions on hot paths (> 1000/s) must set `sampling_rate < 1.0`.
- Sampling is **deterministic per process** — the helper hashes the
  current tag tuple and keeps emissions from a fixed fraction of
  tuples. That keeps the distribution representative while cutting
  volume.
- The helper multiplies the retained sample's weight by
  `1 / sampling_rate` so p95/p99 estimates remain correct.

```python
SEARCH_API_LATENCY = MetricDef.latency(
    "search_api.query.duration",
    owner="platform",
    means="Wall-clock duration of a single search API call.",
    tags={"result_bucket": "count_bucket"},
    emit_frequency="per_event",
    sampling_rate=0.1,           # hot: keep 10%
    max_rate_hz=500.0,           # hard cap per process
)
```

## Loop-safe aggregation

Counters and distributions inside `for`/`while` bodies are a classic
Sentry-bill-blowup. The `loop_policy` field + two context managers
handle it:

### `loop_policy="aggregate_only"` (default)

- CI requires any emission inside a loop to be wrapped in
  `AggregatingCounter` (counters) or `DurationAccumulator`
  (distributions), OR marked with the escape comment
  `# instrumentation: loop-aggregate` + a rationale.
- One emission fires on `__exit__`, carrying the aggregated total.

### `loop_policy="forbidden"`

- CI refuses **any** emission inside a loop for this metric. Use for
  metrics where per-iteration emission is never semantically correct
  (e.g., a `per_request` counter that would dominate the series if
  emitted from a batch loop).

### `loop_policy="allowed"`

- Opt-in for rare metrics where per-iteration emission is genuinely
  the intent (e.g., a distribution of per-row processing time where
  each row is a legitimate event). Use sparingly; ask in review why
  an aggregator isn't enough.

### `AggregatingCounter`

```python
with AggregatingCounter(PRIMARY_SIGNAL_FALLBACK, tags={"reason": "primary_empty"}) as c:
    for item in items:
        if not item.primary_signal:
            c.add(1)
    # __exit__ emits one counter with the accumulated total.
```

### `DurationAccumulator`

Collects per-iteration durations into a single distribution sample at
exit (a single value representing the *total* time in the loop),
rather than emitting one distribution per iteration.

```python
with DurationAccumulator(ROW_PROCESSING_TOTAL_DURATION, tags={...}) as d:
    for row in rows:
        started = time.monotonic()
        process(row)
        d.add_ms((time.monotonic() - started) * 1000)
```

## Rate limiter

The emission helpers carry a per-process token bucket keyed by metric
name:

- `max_rate_hz` defaults to `None` (unlimited). Set it on any metric
  that could burst — especially external-API clients, retry loops,
  and request middleware.
- When a metric exceeds `max_rate_hz`, further emissions in the
  current second are dropped.
- Dropped emissions increment a `correctness` counter named
  `instrumentation.rate_limit.drop_count` tagged with
  `metric` — **this single tag is exempt from the anti-cardinality
  rule** because the registry is finite.

## Production vs. test behavior

The helper API validates every emission against the `MetricDef` at
call time. Validation failures include: unknown tag key, tag value
outside constraints, wrong `kind`, loop-policy violation,
`cardinality="high"`, duration metric emitted with a non-ms unit,
failure counter without a `failure_class` tag.

- In **pytest** (detected via `"pytest" in sys.modules`) and when
  `settings.environment != "production"`, validator failures **raise**
  `InstrumentationContractError`. Tests fail fast; dev catches misuse
  immediately.
- In **production**, validator failures drop the emission silently
  and increment `instrumentation.violation.count` tagged with the
  violated rule. Observability never crashes the service.

## Cost-model checklist

Before shipping a new metric on a high-traffic path, check:

- [ ] `emit_frequency` set correctly for the actual firing rate.
- [ ] `sampling_rate` set for distributions expected > 1000/s.
- [ ] `max_rate_hz` set for anything that could burst.
- [ ] `loop_policy` set — if the metric will ever appear in a loop,
      pick `aggregate_only` (default) and wrap it.
- [ ] Is a trace span (via `sentry_sdk.start_span`) a better fit than
      a metric for this signal? If the signal is per-operation detail
      rather than aggregate, a span is cheaper and richer.
