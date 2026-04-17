# Python reference implementation

This directory is the **canonical reference** for the
`sentry-instrumentation` skill. Every rule in `references/` has a
concrete Python drop-in here.

Ports to other languages (TypeScript v0.2, Go v0.3, …) preserve the
shapes in this directory — same constructors, same 13 CI checks,
same `FailureClass` taxonomy — under idiomatic names.

## Drop-in mapping

Copy each file to the target path in your project, then rename
`yourapp` to your package root.

| Example file | Target path | Purpose |
|---|---|---|
| `metric_def.py` | `yourapp/shared/metrics.py` | `MetricDef` schema + 5 classmethod constructors + `REGISTRY` set |
| `metric_tags.py` | `yourapp/shared/metric_tags.py` | Approved bucket functions (`status_code_class`, `size_bucket`, `count_bucket`, `attempt_bucket`, `bool_tag`) |
| `failure_taxonomy.py` | `yourapp/shared/failure_taxonomy.py` | `FailureClass` enum + `classify()` + `register()` |
| `emission_module.py` | `yourapp/observability.py` | `init_sentry` + validating `emit_*` helpers + `AggregatingCounter` / `DurationAccumulator` |
| `http_middleware.py` | `yourapp/middleware/observability.py` | `ObservabilityMiddleware` (Starlette/FastAPI) |
| `external_api_client.py` | `yourapp/services/providers/instrumented_http_client.py` | `InstrumentedHttpClient` base class (httpx) |
| `workflow_decorator.py` | `yourapp/services/<workflow>/instrumentation.py` | `@instrumented_step` decorator |
| `retry_loop.py` | `yourapp/services/retry.py` | `retry_with_instrumentation` async iterator |
| `fallback_path.py` | `yourapp/observability.py` or `yourapp/shared/fallback.py` | `record_fallback(metric, reason=...)` |
| `ci_gate.py` | `scripts/check_metrics.py` | 13-check AST gate |
| `test_gates.py` | `tests/test_observability_gates.py` | Contract-level pytest cases |

## Dependency footprint

Required:

- `sentry-sdk>=2.0` (Sentry Metrics API)

Optional — only if you use the matching surface pattern:

- `starlette` — for `http_middleware.py` (also works under FastAPI,
  which uses Starlette internally)
- `httpx` — for `external_api_client.py`

All other examples are pure-stdlib Python.

Python runtime: **3.11+**. The examples use `StrEnum` (added in
3.11) and PEP-604 union syntax (`X | Y`). For 3.10 support, swap
`StrEnum(str, Enum)` equivalents and import `Optional[T]` / `Union[A,
B]` from `typing`.

## Sentry Metrics API — version caveat

The examples call `sentry_sdk.metrics.count / gauge / distribution`.
Sentry Metrics has moved through beta and had pricing / API
adjustments since 2024. Before shipping:

1. Check your installed `sentry-sdk` version supports the API surface
   used here.
2. Re-verify the current pricing in your Sentry organization settings
   — distribution volume is the primary cost driver, so the
   `sampling_rate` / `max_rate_hz` knobs on each `MetricDef` exist
   precisely to keep that bill bounded.

**Reference version:** `sentry-sdk==2.x` as of April 2026. If you're
on a newer version that renamed the API, preserve the validating-
helper contract in `emission_module.py` (the only place that touches
the raw SDK) and update one module.

## Why Python first

The skill was reverse-engineered from a Python codebase where the
governance grew organically and was then formalized. Python's
runtime type checks + `ast` module let the helper API and CI gate
enforce the same rules at different layers — the examples shipped
here are exactly what's running in production at Torta Studios.

The rules translate directly to other languages (TypeScript's
`ts-morph`, Go's `go/ast`, Ruby's `parser`). Only the syntax changes;
the grammar, shapes, and enforcement surface stay identical. That's
why the rules live in `references/` as prose and the language-
specific drop-in here can be replaced or supplemented without
touching the canonical rules.

## See also

- `../../SKILL.md` — the contract the agent reads
- `../../references/` — the 12 deep-dive docs
- `../../adapters/` — per-agent install notes
