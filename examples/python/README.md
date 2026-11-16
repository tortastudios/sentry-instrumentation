# Python reference implementation

This directory is the **canonical reference** for the
`sentry-instrumentation` skill. Every rule in `references/` has a
concrete Python drop-in here.

Ports to other languages (TypeScript v0.2, Go v0.3, …) preserve the
shapes in this directory — same constructors, same 14 CI checks,
same `FailureClass` taxonomy — under idiomatic names.

Most modules here are **metrics** governance. `ai_agent_spans.py` is the
first **tracing** module — `gen_ai.*` spans for AI agent conversations.
The `gen_ai.*` attribute names are Sentry product contract, so they port
verbatim to any language (only the span-API calls change). See
`../../references/ai-agent-conversations.md`.

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
| `ai_agent_spans.py` | `yourapp/observability/ai_spans.py` | `gen_ai.*` tracing for AI agent conversations (`invoke_agent` / `chat` / `execute_tool` spans + `set_conversation_id`) |
| `ci_gate.py` | `scripts/check_metrics.py` | 14-check AST gate |
| `test_gates.py` | `tests/test_observability_gates.py` | Contract-level pytest cases |
| `test_ci_gate.py` | `tests/test_check_metrics.py` | Tests for the gate itself |

`conftest.py` and `requirements-dev.txt` are for running the examples
in this repo, not for dropping in:

```bash
pip install -r examples/python/requirements-dev.txt
pytest examples/python
```

`conftest.py` builds the `yourapp.*` package in memory from the files
here, so the tests exercise the real example code.

## Dependency footprint

Required:

- `sentry-sdk>=2.64.0`. Sentry's docs give 2.44.0 as the minimum for
  `sentry_sdk.metrics` and 2.64.0 for gen_ai spans to appear in
  Conversations. **Tested version: `sentry-sdk==2.75.0`.**

Optional — only if you use the matching surface pattern:

- `starlette` — for `http_middleware.py` (also works under FastAPI,
  which uses Starlette internally)
- `httpx` — for `external_api_client.py`

All other examples are pure-stdlib Python.

`ai_agent_spans.py` needs **tracing enabled** in `sentry_sdk.init`
(`traces_sample_rate` or a `traces_sampler`) — conversations are built
from spans. The conversation-id helper wraps `sentry_sdk.ai` and
degrades to a no-op on SDKs that predate it.

Python runtime: **3.11+**. The examples use `StrEnum` (added in
3.11) and PEP-604 union syntax (`X | Y`). For 3.10 support, swap
`StrEnum(str, Enum)` equivalents and import `Optional[T]` / `Union[A,
B]` from `typing`.

## Sentry API surface used

Checked against `sentry-sdk==2.75.0` and
<https://docs.sentry.io/platforms/python/metrics/>:

```python
sentry_sdk.metrics.count(name, value, unit=None, attributes=None)
sentry_sdk.metrics.gauge(name, value, unit=None, attributes=None)
sentry_sdk.metrics.distribution(name, value, unit=None, attributes=None)
```

- The keyword is `attributes=`. There is no `tags=` parameter.
- Metrics are on by default once the SDK is initialized; no
  `enable_metrics` flag is needed.
- `before_send_metric(metric, hint)` in `sentry_sdk.init` can edit
  attributes or return `None` to drop a metric. `emission_module.py`
  uses it for a name-based kill switch.
- Logs use the top-level `enable_logs=True` option.
- `send_default_pii` is deprecated in 2.75.0 in favour of
  `data_collection`; the example init sets neither, so no `user.*`
  attributes are attached to metrics.

`test_real_sdk_receives_attributes_keyword` pins this call shape, so a
future SDK that changes it fails the suite instead of failing silently
in production (where the helpers swallow SDK exceptions).

Pricing: Sentry bills Application Metrics by data volume (5 GB
included, then $0.50/GB pay-as-you-go —
<https://docs.sentry.io/pricing/>). The `sampling_rate` /
`max_rate_hz` / `loop_policy` knobs on each `MetricDef` exist to bound
that volume. Re-check the pricing page before relying on these numbers.

If you're on a newer SDK that renamed the API, `_sink` in
`emission_module.py` is the only function that touches the raw SDK —
update that one function.

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
- `../../references/` — the 13 deep-dive docs
- `../../adapters/` — per-agent install notes
