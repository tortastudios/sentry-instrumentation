# Signal model — the `MetricDef` schema

Every metric is a frozen `MetricDef` instance carrying the metadata
required to interpret, validate, govern, and cost it.

## Fields

```python
@dataclass(frozen=True, eq=False)
class MetricDef:
    # --- identity (immutable under the same name) ---
    name: str                        # dotted identifier, unique
    kind: Literal["counter", "gauge", "distribution"]
    unit: str                        # "ms", "bytes", "tokens", "count", "none"
    purpose: Literal["outcome", "latency", "load", "resource", "correctness"]

    # --- tagging ---
    allowed_tags: frozenset[str]
    tag_constraints: Mapping[str, frozenset[str] | str]
    cardinality: Literal["low", "medium"]

    # --- cost model ---
    emit_frequency: Literal["per_request", "per_step", "per_event", "periodic"]
    sampling_rate: float = 1.0
    max_rate_hz: float | None = None
    loop_policy: Literal["forbidden", "aggregate_only", "allowed"] = "aggregate_only"

    # --- operational + ownership ---
    operational_meaning: str
    owner: str

    # --- lifecycle ---
    version: int = 1
    deprecated: bool = False
    replaced_by: str | None = None
    retired_at: date | None = None
```

Identity tuple: `(name, kind, unit, purpose, allowed_tags,
tag_constraints)`. Immutable once published — see
`naming-and-lifecycle.md` for the versioning rule.

Equality and hashing are deliberately **name-based**: two `MetricDef`s
with the same name are "the same metric" for registry dedup purposes.
This lets `tag_constraints` be a `Mapping` without breaking hashing,
and makes "is this a duplicate?" a set membership check.

## Ergonomic constructors

Never construct `MetricDef(...)` directly. Use the five classmethods;
each fixes `kind`/`unit`/`purpose` so the call site only states the
knobs that matter for that metric class.

```python
MetricDef.counter(
    name, *, purpose, owner, means, tags=None,
    emit_frequency="per_event", sampling_rate=1.0, max_rate_hz=None,
    loop_policy="aggregate_only", cardinality="low",
    version=1, deprecated=False, replaced_by=None, retired_at=None,
) -> MetricDef                         # kind="counter", unit="count"

MetricDef.latency(
    name, *, owner, means, tags=None, ...
) -> MetricDef                         # kind="distribution", unit="ms", purpose="latency"

MetricDef.gauge(
    name, *, unit, owner, means, tags=None, emit_frequency="periodic", ...
) -> MetricDef                         # kind="gauge", purpose="load"

MetricDef.resource(
    name, *, unit, owner, means, tags=None, ...
) -> MetricDef                         # kind="counter", purpose="resource"

MetricDef.failure_counter(
    name, *, owner, means, tags=None, ...
) -> MetricDef                         # kind="counter", purpose="outcome";
                                       # allowed_tags ⊇ {"failure_class"}
```

`means` is the `operational_meaning` — **always required**, written to
be readable in six months by somebody who wasn't on the PR. Include
the division for rates ("divide by X for hit-rate"), start→stop
boundaries for durations, and the operational failure mode for
outcome counters.

## Examples

```python
# Counter — outcome
CACHE_HIT = MetricDef.counter(
    "cache.hit.count",
    purpose="outcome",
    owner="platform",
    means="Cache lookup returned a hit; divide by cache.lookup.count for hit-rate.",
    tags={"backend": frozenset({"redis", "memory"})},
    emit_frequency="per_request",
)

# Distribution — latency
EXTERNAL_API_DURATION = MetricDef.latency(
    "external_api.request.duration",
    owner="platform",
    means="Wall-clock duration of a single external API call, including cache miss path.",
    tags={"cache_status": frozenset({"hit", "miss", "skipped", "error"})},
    emit_frequency="per_event",
    sampling_rate=1.0,
)

# Gauge — load
QUEUE_DEPTH = MetricDef.gauge(
    "worker.queue.depth",
    unit="items",
    owner="platform",
    means="Currently-queued items in the ingest queue, sampled every 10s. (Workflow engine e.g., Hatchet, Celery, Temporal, Sidekiq, Inngest, BullMQ.)",
    tags={"queue": frozenset({"default", "priority"})},
    emit_frequency="periodic",
)

# Counter — resource
EXTERNAL_API_QUOTA = MetricDef.resource(
    "external_api.quota.units",
    unit="units",
    owner="platform",
    means="External API quota units consumed per call. Replace the budget value with your dependency's cap (e.g., daily API quota, project-level token budget for most LLM vendors).",
    tags={"endpoint": frozenset({"list", "detail", "search"})},
    emit_frequency="per_event",
)

# Counter — failure outcome
WORKER_JOB_FAILURES = MetricDef.failure_counter(
    "worker.job.failure.count",
    owner="platform",
    means="A workflow step raised an exception after its retry budget. Replace the stage enumeration below with your domain's workflow stage names.",
    tags={"stage": frozenset({"ingest", "transform", "publish"})},
    emit_frequency="per_step",
)
```

## Identity field notes

- `name` format: `<domain>.<object>.<action>[.<type-suffix>]`. Lowercase,
  dotted, no abbreviations outside the domain vocabulary. The type
  suffix disambiguates similarly-named metrics that differ by kind:
  `.count`, `.duration_ms`, `.value`, `.units`.
- `kind` and `unit` are set by the constructor. If you think you need
  a counter in seconds, you actually need a distribution. If you think
  you need a gauge in counts, you probably want a counter.
- `purpose` is the semantic bucket. Exactly one purpose fits a metric;
  if two fit, it's actually two metrics. See `metric-classes.md`.

## Tagging field notes

- `allowed_tags` is derived from `tag_constraints` — don't pass it
  manually through the constructors.
- `tag_constraints` maps tag key → `frozenset[str]` (enumerated
  values) or `str` (name of an approved bucket function in
  `metric_tags.py`). See `tagging-and-cardinality.md` for which bucket
  functions are approved.
- `cardinality` defaults to `"low"` (≤ 20 combinations). Use
  `"medium"` (≤ ~200) only with an explicit justification in `means=`.
  `"high"` is forbidden.

## Cost field notes

- `emit_frequency` tells the reader (and the rate-limiter budget) how
  often this metric fires: `per_request`, `per_step`, `per_event`,
  `periodic`.
- `sampling_rate` < 1.0 is required for distributions on hot paths (>
  1000/s). The helper API reweighs the emission deterministically per
  tag hash.
- `max_rate_hz` is the per-process hard cap. The emission helper drops
  beyond this and emits a `correctness` counter.
- `loop_policy` controls CI enforcement of loop-safe emission. See
  `cost-model.md`.

## Lifecycle field notes

- `version` starts at 1. A new versioned metric (`<name>.v2`) starts
  at `version=2` on the new name; the old name keeps `version=1` with
  `deprecated=True`.
- `deprecated=True` + `replaced_by="<new-name>"` + `retired_at=<date>`
  are set together. The CI gate refuses a PR that splits them.
- `retired_at` in the past is a CI failure — forces removal on
  schedule.
