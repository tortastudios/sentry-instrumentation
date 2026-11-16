---
name: sentry-instrumentation
description: Rules and examples for adding Sentry instrumentation the right way — metrics and tracing. Covers how to name a counter, gauge, or duration metric; which attributes are group-by tags (closed lists) versus debug context (ids); how to track failures with a small fixed list of error types instead of raw exception strings; how to add metrics around HTTP routes, external API calls, workflow steps, retry loops, and fallback paths without copy-pasting emit calls everywhere; and how to instrument AI agent conversations with `gen_ai.*` spans (invoke_agent / chat / execute_tool, conversation ids, token accounting) for Sentry's Conversations view. Ships a CI check that blocks bad metrics before merge. Use this when someone asks to "instrument" code, "add a metric", "track duration", "count failures", "emit a counter/gauge/distribution", "add a span", "observe" a workflow step, add a route, external API client, retry loop, or fallback path, or "instrument an AI agent / LLM call / tool call", "track conversations", or "trace an agent". Python reference examples included; the same shapes work in any language.
---

# Sentry Instrumentation

Two surfaces: **system metrics** (counter / gauge / distribution, duration, failure, resource) and **tracing** (currently the `gen_ai.*` spans for AI agent conversations — see rule 7). Product-analytics events (clicks, funnels, flag exposure) belong in your product-analytics tool — never in Sentry. Python under `examples/python/` is the canonical reference; other languages port the same shapes under idiomatic names.

Do not invoke for product-analytics changes. Stop and use the right tool.

## Decision rules

1. **New metric?** Read `references/signal-model.md` and pick a classmethod constructor (`MetricDef.counter|latency|gauge|resource|failure_counter`). Register in the project's metric registry. **Never** call an emission helper with a raw string or a dynamically-assembled name.
2. **Attributes?** Two kinds, both declared on the `MetricDef` (see `references/tagging-and-cardinality.md`). **Group-by tags** (`tags=`) — what dashboards and alerts group on — are closed sets: enumerate the values or route through a bucket function. **Debug context** (`context=`) — ids like `account_id`, `project_id`, `order_id` used to find who was affected — are declared by key and free-valued; Sentry stores full metric events, so they are queryable. Never put an id in `tags=`. Never put free-form text, exception strings, emails or raw URLs on a metric in either role. Don't add `trace_id` — every metric already carries it.
3. **Inside a loop?** Use `AggregatingCounter` or `DurationAccumulator` (see `references/cost-model.md`) — Sentry bills metrics by data volume. If the metric's `loop_policy` is `"forbidden"` the CI gate refuses any emission inside a `for`/`while` body for that metric.
4. **New surface (HTTP route / external API / workflow step / retry / fallback)?** Use the matching reusable pattern from `references/surface-patterns.md`. Don't hand-roll the emissions.
5. **Changing a metric's meaning, unit, or tag shape?** It's a new versioned metric. See `references/naming-and-lifecycle.md`.
6. **Failure counter?** Build with `MetricDef.failure_counter(...)` and emit with `emit_failure(metric, failure=classify(exc), tags=...)`. Never pass `str(exc)` as a tag. See `references/failure-taxonomy.md`.
7. **AI agent / LLM call / tool call / conversation?** This is **tracing**, not metrics. Use `gen_ai.*` spans (`invoke_agent` / `chat` / `execute_tool`) and set `gen_ai.conversation.id` per turn so Sentry's Conversations view (Explore → Agents) groups the session. See `references/ai-agent-conversations.md` and `examples/python/ai_agent_spans.py`. Message bodies go on **span attributes only** — never on a metric. The conversation id is never a metric `tags=` value (declare it as `context=` if a metric needs it). Still emit a governed `failure_counter` on the failure path.

## Language detection

Detect the project language from manifest files, then extend any existing observability layer you find (`observability.py` / `observability.ts` / `metrics/` package). If none exists, scaffold from the matching example directory.

```
pyproject.toml / setup.py  → Python. Use examples/python/.
package.json               → TypeScript/JavaScript. Port from examples/python/ shapes.
go.mod                     → Go. Port from examples/python/ shapes.
Gemfile                    → Ruby. Port from examples/python/ shapes.
pom.xml / build.gradle     → Java/Kotlin. Port from examples/python/ shapes.
```

For ports: preserve the five constructors, the `FailureClass` taxonomy values, the 14 CI gate checks, and the emission-boundary rules. Names become idiomatic (`emit_counter` → `emitCounter`, `@instrumented_step` → `instrumentedStep(fn)`, etc.).

## Python project paths (canonical reference)

Replace `yourapp` with the project's package root on first use.

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
AI agent spans:     yourapp/observability/ai_spans.py
CI gate:            scripts/check_metrics.py
```

## References (load on demand)

| Topic | Reference | Example |
|---|---|---|
| Charter & scope | `references/charter.md` | — |
| `MetricDef` schema + constructors | `references/signal-model.md` | `examples/python/metric_def.py` |
| Five metric classes by purpose | `references/metric-classes.md` | — |
| Kind semantic rules (counter/gauge/distribution) | `references/semantic-rules.md` | — |
| Naming + lifecycle (version suffix, retired_at) | `references/naming-and-lifecycle.md` | — |
| Group-by tags vs debug context + bucket fns | `references/tagging-and-cardinality.md` | `examples/python/metric_tags.py` |
| Cost model (what Sentry bills, sampling, rate limit, aggregation) | `references/cost-model.md` | `examples/python/emission_module.py` |
| Emission boundaries (where to emit) | `references/emission-boundaries.md` | — |
| Failure taxonomy (`FailureClass` + `classify`) | `references/failure-taxonomy.md` | `examples/python/failure_taxonomy.py` |
| Reusable surface patterns | `references/surface-patterns.md` | `examples/python/http_middleware.py`, `examples/python/external_api_client.py`, `examples/python/workflow_decorator.py`, `examples/python/retry_loop.py`, `examples/python/fallback_path.py` |
| AI agent conversations (`gen_ai.*` tracing) | `references/ai-agent-conversations.md` | `examples/python/ai_agent_spans.py` |
| Emission helpers + validators | — | `examples/python/emission_module.py` |
| CI enforcement gate (14 AST checks) | `references/enforcement.md` | `examples/python/ci_gate.py` |
| Test gates | `references/enforcement.md` | `examples/python/test_gates.py`, `examples/python/test_ci_gate.py` |
| PR review rubric | `references/review-rubric.md` | — |
