# Cost model

Every `MetricDef` declares its cost shape — `emit_frequency`,
`sampling_rate`, `max_rate_hz`, `loop_policy`. The helper API and CI
gate enforce those declarations so a single hot-path site can't blow
up the Sentry bill.

## What Sentry bills

Application Metrics is billed by **data volume**, not by series or by
distinct attribute values. Every plan includes 5 GB; beyond that it is
$0.50/GB, charged to the pay-as-you-go budget
([pricing](https://docs.sentry.io/pricing/)). Once the included volume
and the PAYG budget are used up, further data is dropped.

Two consequences shape everything below:

- **Volume is events × event size.** The number of emissions is the
  lever you control most directly. Attributes add to the size of each
  event; Sentry does not publish per-event or per-attribute byte
  figures, so this skill makes no numeric claim about them.
- **Nothing server-side catches a burst for you.** Spike Protection
  "currently applies to errors, transactions or spans, and attachments"
  ([docs](https://docs.sentry.io/pricing/quotas/spike-protection/)) —
  not metrics. A runaway loop spends budget until someone notices.

Sentry's own list of ways to reduce metric quota usage
([quota guide](https://docs.sentry.io/pricing/quotas/manage-application-metrics-quota/))
is: emit with intent, keep cardinality in check, filter with
`before_send_metric`, disable in non-critical environments, watch usage
stats, set quota alerts. The controls here are this skill's way of
applying the first three in code. Loop aggregation, client-side
sampling and the rate cap are not Sentry features; they are
volume-reduction techniques that follow from per-GB billing.

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

- Distributions on hot paths (> 1000/s) should set `sampling_rate < 1.0`.
- Sampling is **uniform random per emission**: every tag combination
  keeps roughly `sampling_rate` of its samples, so percentiles stay
  representative.
- **Sampled metrics under-report volume.** `count()`, `sum()` and
  rates over a sampled distribution are low by the sampling factor.
  The Python SDK has no public way to attach a sample weight to a
  metric (Sentry's event schema has a `client_sample_rate` field, but
  `sentry_sdk.metrics.*` does not expose it as of 2.75.0). Read
  percentiles from the sampled distribution and volumes from the
  paired counter.
- Counters and gauges are never sampled — a sampled counter is just a
  wrong number.
- A sampled-out emission also loses its trace link. Sentry notes that
  metrics are "typically sampled at 100%"; sample only where the
  volume justifies it.

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

Counters and distributions inside `for`/`while` bodies multiply
event volume by the loop length. For a counter this buys nothing:
one event with `value=N` gives the same `sum()` as N events with
`value=1`. The `loop_policy` field + two context managers handle it.

The trade-off under Sentry's event model: an aggregated event links to
one trace/span, and carries one set of attributes. If you need to find
*which* iteration failed, emit per iteration for the failure path only
(failures are rare) and aggregate the success path.

### `loop_policy="aggregate_only"` (default)

- CI requires any emission inside a loop to be wrapped in
  `AggregatingCounter` (counters) or `DurationAccumulator`
  (distributions), OR marked with the escape comment
  `# instrumentation: loop-aggregate` + a rationale.
- One emission fires on `__exit__`, carrying the aggregated total.

### `loop_policy="forbidden"`

- CI refuses **any** emission inside a loop for this metric, even
  inside an aggregator or with the escape comment. Use for
  metrics where per-iteration emission is never semantically correct
  (e.g., a `per_request` counter that would dominate the metric if
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
  current second are dropped. This is the only burst guard metrics
  have (see "What Sentry bills").
- Drops are counted in memory and reported as **one**
  `instrumentation.rate_limit.drop_count` event per metric per window
  (value = number dropped, tagged with `metric`). Reporting each drop
  as its own event would send as much data as the limiter saved. Call
  `flush_rate_limit_drops()` at shutdown to report the last window.
- The limiter applies to counters and distributions. Gauges are
  `periodic` by contract and are not limited.

## Kill switch: `before_send_metric`

Sentry calls SDK-side filtering "the most effective way to reduce your
Application Metrics quota usage". The emission module wires a
`before_send_metric` hook that drops any metric named in
`DROPPED_METRIC_NAMES` — the fastest way to stop paying for a metric
that turned out to be noise, ahead of its proper deprecation. Sentry
also has server-side inbound filters by metric name (glob patterns) in
project settings, which need no deploy.

## Production vs. test behavior

The helper API validates every emission against the `MetricDef` at
call time. Validation failures include: unknown tag key, tag value
outside constraints, undeclared context key, context value that is
not a small primitive, wrong `kind`, duration metric emitted with a
non-millisecond unit, failure counter without a `failure_class` tag.

- In **pytest** (detected via `"pytest" in sys.modules`) and when
  `settings.environment != "production"`, validator failures **raise**
  `InstrumentationContractError`. Tests fail fast; dev catches misuse
  immediately.
- In **production**, validator failures drop the emission silently
  and increment `instrumentation.violation.count` tagged with the
  metric name and a fixed rule code (`unknown_tag_key`,
  `tag_value_outside_constraints`, `unknown_context_key`, …) — never
  the error message text. Observability never crashes the service.

## Cost-model checklist

Before shipping a new metric on a high-traffic path, check:

- [ ] `emit_frequency` set correctly for the actual firing rate.
- [ ] `sampling_rate` set for distributions expected > 1000/s.
- [ ] `max_rate_hz` set for anything that could burst.
- [ ] `loop_policy` set — if the metric will ever appear in a loop,
      pick `aggregate_only` (default) and wrap it.
- [ ] `context=` limited to the ids you would actually search by.
- [ ] Is a trace span (via `sentry_sdk.start_span`) a better fit than
      a metric for this signal? Sentry's guidance: metrics for
      application health signals, traces for request flow, logs for
      forensic detail.
