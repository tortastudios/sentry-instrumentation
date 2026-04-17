---
name: sentry-instrumentation
description: Governed Sentry instrumentation layer for system-behavior tracking — MetricDef schema with ergonomic constructors (counter/latency/gauge/resource/failure_counter), low-cardinality tagging with approved bucket functions, bounded failure taxonomy, emission-boundary rules, cost model (sampling, rate limits, loop aggregation), lifecycle and versioning rules, reusable surface patterns (HTTP middleware, external API client, workflow decorator, retry loop, fallback helper), CI enforcement, and a review rubric. Auto-invoke when adding or modifying code that emits a metric, measures duration, counts failures, wraps a workflow step, adds a route or external-API client, adds a retry loop or fallback path, or whenever the user says "instrument", "emit a metric", "add a gauge/counter/distribution", "add a span", "observe", or "track system behavior". Canonical reference ships in Python (`examples/python/`); the rules and shapes port to any language. Does NOT cover product analytics — PostHog events live in a sibling skill.
---

# Sentry Instrumentation

**Scope:** Sentry (system behavior) only. Product analytics (PostHog
events) belong in the sibling `posthog-analytics` skill. If the change
touches a user-facing funnel event, stop and pick the right skill.

**Canonical reference:** Python, under `examples/python/`. The rules
in `references/` are language-neutral — ports to TypeScript, Go,
Ruby, Java, etc. keep the same shapes (same constructors, same 13
CI checks, same `FailureClass` taxonomy) under idiomatic names. When
no reference implementation exists for the target language yet, use
Python as the architectural spec and port the shapes.

## Where to start (5 bullets for the agent)

1. **Identify the project's language and workflow conventions.** Look
   for `pyproject.toml` / `package.json` / `go.mod` / `Gemfile` /
   `pom.xml`. Note the test runner, linter, and CI wiring — they're
   how the instrumentation gate will be enforced.
2. **Grep for an existing observability layer first.** Extend it
   rather than creating a parallel one. A file named
   `observability.py` / `observability.ts` / `observability.go`, or a
   `metrics/` package, is the prime signal.
3. **Pick the constructor that matches the metric's purpose** (see
   `references/signal-model.md` + `references/metric-classes.md`). Do
   not open-code a counter / distribution / gauge literal.
4. **Use the matching surface pattern** (middleware, decorator, base
   class) from `references/surface-patterns.md` — don't hand-roll
   emissions at call sites. Using the pattern is always less code.
5. **Register in the project's `MetricDef` registry.** CI gate
   enforces identity + lifecycle rules on the registry contents.

## Charter (read before writing any metric)

Every metric emitted by this service must be:

1. **Semantically precise** — exactly one of five purposes
   (outcome / latency / load / resource / correctness), exactly one
   kind (counter / gauge / distribution), a mandatory unit.
2. **Bounded** — tag values come from a small enumerated set or an
   approved bucket function. No raw user ids, URLs, exception strings,
   or timestamps.
3. **Enforceable** — defined once as a `MetricDef`, emitted via the
   validating helper API, checked by CI against the registry before
   merge.
4. **Versioned** — identity tuple is immutable under the same name.
   Meaning change = new name with a `.v2` suffix, 14-day overlap,
   `retired_at` date.
5. **Cost-aware** — declares its `emit_frequency`, `sampling_rate`,
   `max_rate_hz`, and `loop_policy`. Distributions on hot paths sample;
   counters in loops aggregate.
6. **Ergonomic** — the correct path is the easiest path. Build
   `MetricDef`s through `.counter` / `.latency` / `.gauge` / `.resource`
   / `.failure_counter`. Emit through `emit_counter` / `emit_latency` /
   `emit_failure` / `time_latency`. Use the surface patterns
   (`ObservabilityMiddleware`, `InstrumentedHttpClient`,
   `@instrumented_step`, `retry_with_instrumentation`, `record_fallback`)
   — they bake in the right emissions so call sites never hand-roll
   them.

**Does NOT define:** dashboards, alert rules, SLO thresholds, on-call
policy, or product analytics. Those depend on this layer being clean.

## When this skill applies (auto-invocation triggers)

Invoke for any change that:

- Adds or modifies code that emits a Sentry metric.
- Measures a duration, counts failures, or reports a resource amount
  (tokens, bytes, API units).
- Wraps a workflow step (Hatchet, Celery, Temporal, Sidekiq, Inngest,
  BullMQ, or equivalent).
- Adds a route, middleware, or external-API client.
- Adds a retry loop, fallback path, or degradation branch.
- Contains the words "instrument", "emit a metric", "add a
  gauge/counter/distribution", "add a span", "observe", "track system
  behavior", "record timing", or "count failures".

Do **not** invoke for product-analytics changes (button click counts,
funnel events, feature-flag exposure). Those go to
`posthog-analytics`.

## Decision rules

1. **New metric?** Read `references/signal-model.md` + pick a
   classmethod constructor (`MetricDef.counter|latency|gauge|resource|failure_counter`).
   Register in the project's metric registry. **Never** call an emission
   helper with a raw string or a dynamically-assembled name.
2. **Tag values?** Either enumerate them in `MetricDef.tag_constraints`
   or route through a bucket function from
   `references/tagging-and-cardinality.md`.
3. **Inside a loop?** Use `AggregatingCounter` or `DurationAccumulator`
   (see `references/cost-model.md`). If the metric's `loop_policy` is
   `"forbidden"` the CI gate refuses any emission inside a `for`/`while`
   body for that metric.
4. **New surface (HTTP route / external API / workflow step / retry /
   fallback)?** Use the matching reusable pattern from
   `references/surface-patterns.md`. Don't hand-roll the emissions.
5. **Changing a metric's meaning, unit, or tag shape?** It's a new
   versioned metric. See `references/naming-and-lifecycle.md`.
6. **Failure counter?** Build with `MetricDef.failure_counter(...)` and
   emit with `emit_failure(metric, failure=classify(exc), tags=...)`.
   Never pass `str(exc)` as a tag. See
   `references/failure-taxonomy.md`.

## Detect-or-create

Detect the project language first, then look for an existing
observability layer matching that language's conventions. If you find
one, extend it. If not, scaffold from the matching example under
`examples/<language>/` and rename `yourapp` to the project's package
root.

```
pyproject.toml / setup.py  → Python. Use examples/python/.
package.json (TS or JS)    → TypeScript/JavaScript. v0.2 — port from
                             examples/python/ shapes.
go.mod                     → Go. v0.2 — port from examples/python/
                             shapes.
Gemfile                    → Ruby. port from examples/python/ shapes.
pom.xml / build.gradle     → Java/Kotlin. port from examples/python/
                             shapes.
```

For ports: preserve the five constructors, the `FailureClass`
taxonomy values, the 13 CI gate checks, and the emission-boundary
rules. Names become idiomatic (`emit_counter` → `emitCounter`,
`@instrumented_step` → `instrumentedStep(fn)` higher-order fn, etc.).

## Sections (detailed references)

| Topic | Reference | Example |
|---|---|---|
| Charter & scope | `references/charter.md` | — |
| `MetricDef` schema + constructors | `references/signal-model.md` | `examples/python/metric_def.py` |
| Five metric classes by purpose | `references/metric-classes.md` | — |
| Kind semantic rules (counter/gauge/distribution) | `references/semantic-rules.md` | — |
| Naming + lifecycle (version suffix, retired_at) | `references/naming-and-lifecycle.md` | — |
| Tagging + cardinality policy + bucket fns | `references/tagging-and-cardinality.md` | `examples/python/metric_tags.py` |
| Cost model (sampling, rate limit, aggregation) | `references/cost-model.md` | `examples/python/emission_module.py` |
| Emission boundaries (where to emit) | `references/emission-boundaries.md` | — |
| Failure taxonomy (`FailureClass` + `classify`) | `references/failure-taxonomy.md` | `examples/python/failure_taxonomy.py` |
| Reusable surface patterns | `references/surface-patterns.md` | `examples/python/http_middleware.py`, `examples/python/external_api_client.py`, `examples/python/workflow_decorator.py`, `examples/python/retry_loop.py`, `examples/python/fallback_path.py` |
| Emission helpers + validators | — | `examples/python/emission_module.py` |
| CI enforcement gate (13 AST checks) | `references/enforcement.md` | `examples/python/ci_gate.py` |
| Test gates | `references/enforcement.md` | `examples/python/test_gates.py` |
| PR review rubric | `references/review-rubric.md` | — |

## Project-specific overrides

On first use in a new project, fill these in once so subsequent
invocations know where to land code. The skill's example files use
`yourapp` placeholders; replace with the actual package root.

### Python (canonical reference — v0.1)

```
Emission module:    yourapp/observability.py
Registry:           yourapp/shared/metrics.py
Tag buckets:        yourapp/shared/metric_tags.py
Failure taxonomy:   yourapp/shared/failure_taxonomy.py
HTTP middleware:    yourapp/middleware/observability.py
Workflow decorator: yourapp/services/<workflow>/instrumentation.py
External API base:  yourapp/services/providers/instrumented_http_client.py
Retry helper:       yourapp/services/retry.py
Fallback helper:    yourapp/observability.py (or yourapp/shared/fallback.py)
CI gate:            scripts/check_metrics.py
```

### TypeScript / Node (v0.2 — port from Python shapes)

```
Emission module:    src/observability.ts
Registry:           src/shared/metrics.ts
Tag buckets:        src/shared/metricTags.ts
Failure taxonomy:   src/shared/failureTaxonomy.ts
HTTP middleware:    src/middleware/observability.ts       (Express/Koa)
                    src/fastify-plugins/observability.ts  (Fastify)
Workflow pattern:   src/workflows/<workflow>/instrumentation.ts
External API base:  src/providers/instrumentedHttpClient.ts
CI gate:            scripts/check-metrics.ts              (ts-morph / ast-grep)
```

### Go (v0.2 — port from Python shapes)

```
Emission package:   internal/observability/metrics.go
Registry:           internal/metrics/registry.go
Tag buckets:        internal/metrics/tags.go
Failure taxonomy:   internal/metrics/failure.go
HTTP middleware:    internal/middleware/observability.go  (net/http / chi / echo)
Worker pattern:     internal/workers/<worker>/instrumentation.go
External API:       internal/providers/roundtripper.go    (http.RoundTripper wrapper)
CI gate:            scripts/check_metrics.go              (go/ast)
```

## Quality-gate checklist

Before finalizing a PR that touches instrumentation, walk the review
rubric (full version in `references/review-rubric.md`):

- [ ] Right `kind` for the meaning (counter / gauge / distribution)?
- [ ] Name matches `<domain>.<object>.<action>[.<type-suffix>]` and fits
      `purpose`?
- [ ] All tag keys in `MetricDef.allowed_tags`; values enumerated or
      from an approved bucket function?
- [ ] Emission at a documented boundary / uses a canonical surface
      pattern?
- [ ] Duplicative with an existing `MetricDef`? (Search the registry.)
- [ ] `operational_meaning` unambiguous; will it be interpretable in
      six months?
- [ ] `cardinality="medium"` justified in `means=`?
- [ ] Failure metric uses `emit_failure(...)` + a `FailureClass` value?
- [ ] Inside a loop → uses `AggregatingCounter` / `DurationAccumulator`?
- [ ] Hot path → `sampling_rate` / `max_rate_hz` set?
- [ ] Changing an existing metric → is it actually a new versioned
      entry, with `retired_at` on the old one?
