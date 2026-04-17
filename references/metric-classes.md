# Five metric classes by purpose

Exactly five `purpose` values are allowed. Every metric fits one; if
two fit, it's actually two metrics. A mis-categorized metric corrupts
the dashboards that consume it.

## `outcome`

**Covers:** monotonic event counts — success, failure, timeout,
classified error. Always a counter.

**Sub-types:**
- Success counters (e.g., `cache.hit.count`).
- Failure counters — always built via
  `MetricDef.failure_counter(...)`, always tagged with a
  `FailureClass` value, never tagged with a raw exception string.

**Examples:** `api.request.count`, `worker.job.failure.count`,
`cache.lookup.count`.

**Dashboards derive rates by dividing:** `success_count / total_count`,
`failure_count / total_count`. That's why an outcome counter is
meaningful without a unit beyond `count`.

## `latency`

**Covers:** sampled durations, always distributions, always in
milliseconds. Built via `MetricDef.latency(...)`.

**The start→stop boundary is the metric's identity.** A metric that
measures "request enters middleware → response leaves middleware" is
a different metric from "handler started → handler returned", even if
the code looks similar. Describe the boundary in `means=`.

**Examples:** `api.request.duration`, `worker.job.duration`,
`external_api.request.duration`.

## `load`

**Covers:** currently-in-flight or currently-occupied quantities.
Always a gauge, always sampled on a schedule.

**Not a cumulative count.** If the value can only go up, it's a
counter, not a load gauge.

**Examples:** `worker.queue.depth`, `db.pool.in_use`,
`http.connections.active`.

## `resource`

**Covers:** quantities of a consumable budget drawn down per unit of
work. Always a counter (aggregated over time), with a unit that names
the budget.

**Why it's distinct from `outcome`:** resource counters answer "how
much did we spend" not "how often did event X happen". Dashboards sum
rather than rate.

**Examples:** `external_api.quota.units`, `llm.token.input.count`,
`llm.token.output.count`, `storage.bytes.written`.

## `correctness`

**Covers:** violations that don't crash the service but invalidate
assumptions. Think "we parsed OK but the schema was wrong" or "the
code took a fallback path that means something upstream mis-provided
data".

**Why it's distinct from `outcome` failure counters:** a correctness
event isn't a failure — the operation completed. It's a silent signal
that something upstream (data, config, dependency) is drifting.

**Examples:**
- `instrumentation.violation.count` (helper API rejected a tag in
  production).
- `parse.fallback.count` (primary parser failed, fallback succeeded).
- `taxonomy.unknown.count` (failure classified as `UNKNOWN` — the
  rate is its own SLI).

## Picking the right class

| Question | If yes, purpose is |
|---|---|
| Am I counting events (success or failure)? | `outcome` |
| Am I measuring a start→stop duration? | `latency` |
| Am I reporting a currently-occupied quantity? | `load` |
| Am I reporting a consumed budget? | `resource` |
| Did something silently go wrong without failing? | `correctness` |

If you're still torn, grep the registry first — the metric you want
may already exist.
