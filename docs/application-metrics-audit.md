# Audit: this skill vs. Sentry's Application Metrics model

Date: 2026-11-16. Scope: every rule, rationale and example in the repo
that depends on how Sentry stores, queries or bills metrics, plus the
`gen_ai.*` tracing reference.

The skill was written against a time-series cost model, where each
distinct tag combination is its own billable series. Sentry's current
product stores each metric emission as a full event and bills by data
volume. This document records what that changes, claim by claim, with
the Sentry page behind each verdict.

Labels: **correct** (matches the sources), **outdated** (was reasonable
under the old model), **wrong** (contradicted by a source or by the
code), **unverifiable** (no primary source found either way).

## Sources

| Key | Page |
|---|---|
| PRODUCT | <https://docs.sentry.io/product/explore/metrics/> (canonical `/product/metrics/`) |
| PY | <https://docs.sentry.io/platforms/python/metrics/> |
| ATTR | <https://docs.sentry.io/platforms/python/enriching-events/attributes/> |
| GUIDE | <https://docs.sentry.io/get-started/guides/metrics/> |
| COOKBOOK | <https://sentry.io/cookbook/custom-metrics-dashboard-alerts-nextjs/> |
| BLOG | <https://blog.sentry.io/introducing-application-metrics/> (2026-05-05) |
| PAGE | <https://sentry.io/product/metrics/> |
| SPEC | <https://develop.sentry.dev/sdk/telemetry/metrics/> (v3.1.0) |
| PRICING | <https://docs.sentry.io/pricing/> |
| QUOTA | <https://docs.sentry.io/pricing/quotas/manage-application-metrics-quota/> |
| SPIKE | <https://docs.sentry.io/pricing/quotas/spike-protection/> |
| SEARCH | <https://docs.sentry.io/concepts/search/searchable-properties/metrics/> |
| CONV | <https://docs.sentry.io/product/agents/conversations/> |
| PYAI | <https://docs.sentry.io/platforms/python/agent-tracing/> and `/manual-instrumentation/` |
| AISPEC | <https://develop.sentry.dev/sdk/telemetry/traces/modules/ai-agents/> |
| SDK | `sentry-sdk==2.75.0` source and behaviour, inspected and run locally |

## How Sentry bills metrics

This was the open question going in. It is documented:

- "We bill based on the amount of data processed." Every plan includes
  5 GB of application metrics; additional usage is $0.50/GB and "can
  only be purchased with your PAYG budget." (PRICING)
- A metric event is "a single counter, gauge, or distribution value …
  including metadata like name, kind, value, trace_id, span_id, and
  custom attributes." (QUOTA)
- "High-cardinality custom attributes (user IDs, request IDs, free-form
  strings) inflate metric volume." Sentry's advice is to keep only the
  most valuable and pair them with bounded attributes. (QUOTA)
- Data sent after the included volume and PAYG budget are exhausted is
  dropped and not charged. (PRICING)
- Spike Protection "currently applies to errors, transactions or spans,
  and attachments" — not metrics. (SPIKE)

So: cost is driven by volume (number of events × their size). A new
attribute *value* does not create a billable series. A new attribute
*key* adds bytes to every event that carries it.

**Not documented anywhere we found:** the byte size of a metric event,
how much an attribute adds, any limit on attribute count or value
length, a metrics-specific retention period, or a metrics rate limit.

**Sources disagree:** COOKBOOK says "adding more attributes costs
nothing"; QUOTA says high-cardinality attributes "inflate metric
volume". The skill follows QUOTA because it is the billing document.

## Audit

### Cardinality and attributes

| Repo claim | Where | Verdict | Evidence |
|---|---|---|---|
| "Sentry charges … for every distinct tag tuple"; an unbounded tag "blows up the series count" | `tagging-and-cardinality.md` | **Wrong** | BLOG: "Full events, not pre-aggregated counters". PAGE: "High cardinality is the default, not a limit." PRICING: billed per GB. |
| A user ID as a tag raises the bill 30% a month "because every user makes a new series" | `README.md` | **Wrong** | Same. There is no series. The figure had no source. |
| High-cardinality context goes on spans, never on metric tags; `cardinality="high"` is forbidden | `charter.md`, `tagging-and-cardinality.md`, `SKILL.md` rule 7, `ai-agent-conversations.md` | **Outdated** | PAGE tells users to tag with `customer_id`, route, region, plan, build SHA. BLOG attaches `projectId` and `replayId` to a distribution. |
| User/entity ids are forbidden as tag keys and values | `tagging-and-cardinality.md` | **Outdated** as a ban; **correct** as "not a group-by dimension" | Above, plus QUOTA's "pair with bounded attributes". |
| Raw exception strings, prompt text, free-form strings are forbidden | same | **Correct**, different reason | QUOTA names "free-form strings" as volume inflators. Alert/group-by stability and privacy are this skill's own reasons. |
| Dimensions belong in tags, not in the metric name (dynamic names forbidden) | `naming-and-lifecycle.md`, M013 | **Correct** | COOKBOOK lists baking dimensions into the name as a pitfall. SPEC recommends dotted hierarchical names. |
| Closed lists for failure class, outcome, stage | `failure-taxonomy.md`, everywhere | **Correct** | Monitors and group-by run on attributes (PRODUCT). Justification is alert and dashboard stability, not cost. |
| "The CI gate greps for these literals in `tag_constraints` and call sites" | `tagging-and-cardinality.md` | **Wrong** (about the repo) | `ci_gate.py` contained no such check. |
| `trace_id` / `request_id` as tags are forbidden | same | **Correct**, new reason | Every metric event already carries `trace_id` and `span_id` (PRODUCT, SPEC). Adding them is redundant. |

### API surface

| Repo claim | Where | Verdict | Evidence |
|---|---|---|---|
| Calls `sentry_sdk.metrics.count/gauge/distribution(name=, value=, unit=, attributes=)` | `emission_module.py` | **Correct** | SDK signature: `(name, value, unit=None, attributes=None)`. PY examples use `attributes=`. The code already used `attributes=`; only the helper-level name `tags=` suggested otherwise. |
| "pin `sentry-sdk>=2.0`" | `README.md`, `examples/python/README.md`, `ai_agent_spans.py` | **Wrong** | PY: "supported in Sentry Python SDK version `2.44.0` and above." |
| "Reference version: `sentry-sdk==2.x`" | `examples/python/README.md` | **Outdated** | Now pinned: tested on 2.75.0. |
| "The API has moved through beta" | `README.md` | **Unverifiable** for current status | No page states beta or GA. BLOG (2026-05-05): "We just launched Application Metrics". |
| `_experiments={"enable_logs": True}` | `emission_module.py` | **Outdated** | SDK 2.75.0 has a top-level `enable_logs` option. |
| No `before_send_metric` anywhere | — | **Gap** | PY and QUOTA document it; QUOTA calls SDK filtering "the most effective way to reduce your Application Metrics quota usage". |
| Units `"ms"`, `"bytes"` | `metric_def.py`, docs | **Unverifiable / sources disagree** | PY, GUIDE and the SDK's unit literals use `"millisecond"`, `"byte"`. PRODUCT lists `ms`, `bytes` as examples. SPEC: SDKs "MUST NOT restrict" unit strings. No page says the spellings behave differently. |
| `unit="count"` sent on counters | `metric_def.py` | **Harmless, unverifiable effect** | SPEC: `unit` is "only used for `distribution` and `gauge`". The Python SDK accepts and forwards it. |
| `send_default_pii=False` in init | `emission_module.py` | **Outdated** | SDK 2.75.0 emits a deprecation warning when the option is set at all; `data_collection` replaces it. |

### Default attributes

| Fact | Evidence |
|---|---|
| Always attached: `sentry.environment`, `sentry.release`, `sentry.sdk.name`, `sentry.sdk.version`; backend SDKs add `server.address` | SPEC, PY. Confirmed on SDK 2.75.0 (which also adds `process.runtime.name` / `.version`). |
| `user.id`, `user.name`, `user.email` are attached only when a user is on the scope **and** PII collection is on | SPEC: "MAY attach user information as attributes, guarded by `sendDefaultPii`". SDK source gates on `send_default_pii` / `data_collection["user_info"]`. Confirmed by running it: with a user set and PII off, no `user.*` attribute is sent. PY lists the attributes but does not mention the gate. |
| "SDKs SHOULD minimize the number of default attributes. Metrics cardinality can explode quickly with too many attributes." | SPEC. This is guidance to SDK authors about *defaults*, not a limit on user attributes. It does show Sentry treats attribute count as a real cost. |

The repo said nothing about default attributes. It now does.

### Gauge vs. distribution

| Repo claim | Where | Verdict | Evidence |
|---|---|---|---|
| Distributions give p50/p95/p99 | `semantic-rules.md`, `README.md` | **Correct** | PRODUCT: `p50`, `p75`, `p90`, `p95`, `p99`, `avg`, `sum`, `min`, `max`, `count`. |
| Gauge is current state, never cumulative | `semantic-rules.md` | **Correct** | PY: "Use a gauge when each sample replaces 'what is the value right now?'" |
| (not stated) gauges have no percentiles | — | **Gap** | PY: gauges "cannot produce percentiles". COOKBOOK lists expecting them as a pitfall. |
| Gauge aggregations | — | **Sources disagree** | PRODUCT: `min`, `max`, `avg`, rates. PY: `min`, `max`, `avg`, `sum`, `count`. |
| "The helper multiplies the retained sample's weight by `1 / sampling_rate` so p95/p99 estimates remain correct" | `cost-model.md`, `signal-model.md` | **Wrong** | The code never did this, and `sentry_sdk.metrics.*` has no weight parameter. Sentry's event schema has `client_sample_rate` (PRODUCT), but the Python SDK does not expose it. |

### Volume controls

| Control | Verdict | Reasoning |
|---|---|---|
| Loop aggregation (`AggregatingCounter`, `DurationAccumulator`, M012) | **Still protects something real** | Billing is per GB (PRICING), so N events cost about N times one event. For counters, one event with `value=N` yields the same `sum()`. Cost: the aggregated event links to one trace, not N. |
| Client-side sampling of distributions | **Still useful; implementation was wrong** | Fewer events is less volume. But the helper hashed the tag tuple, so a given tag combination was either always kept or always dropped — at `sampling_rate=0.1` most combinations never appeared in Sentry at all. PRODUCT notes metrics are "typically sampled at 100%". |
| `max_rate_hz` rate cap | **Still protects something real; implementation was wrong** | SPIKE excludes metrics, so nothing server-side stops a burst short of exhausting the budget. But each dropped emission was itself reported as a metric event, so the limiter saved nothing. |
| "Distribution volume is the primary cost driver" | **Unverifiable** | No source prices metric kinds differently. |
| `emit_frequency` caps ("hundreds/s") | **Unverifiable** | The skill's own guidance; no Sentry source. Kept as guidance. |

These three controls are this skill's techniques. Sentry documents none
of them; its own list is: emit with intent, keep cardinality in check,
`before_send_metric`, disable in non-critical environments, monitor
usage, set quota alerts (QUOTA).

### CI gate (M001–M013)

| Check | Rule still right? | Was it implemented? |
|---|---|---|
| M001 SDK isolation | Yes | Yes |
| M002 `emit_*` takes a `MetricDef` symbol | Yes | Yes (false positive on the emission module's own forwarding calls) |
| M003 required fields | Yes | Yes |
| M004 no duplicate names | Yes | Yes |
| M005 name regex | Yes (SPEC recommends dotted names) | Yes |
| M006 medium cardinality justified | Yes for group-by tags; the "series cost" rationale was outdated | Yes |
| M007 tag keys declared | Yes — under the new model this is the check that keeps ids out of group-by tags | **No.** Documented, not coded. |
| M008 deprecation complete | Yes | Yes |
| M009 `retired_at` not past | Yes | Yes |
| M010 identity immutable | Yes | **No.** Docstring mentioned `--baseline`; the flag did not exist. |
| M011 no silent removal | Yes | **No.** Same. |
| M012 loop policy | Yes | Partly: ignored `loop_policy`, so `"allowed"` metrics were flagged. |
| M013 no dynamic names | Yes | Yes |

No check enforced the outdated "no high-cardinality attribute anywhere"
rule in code — that rule lived only in prose and in the runtime
validator's allow-list. No check ID needs retiring.

### Tests

`examples/python/test_gates.py` could not run: it imported a `yourapp`
package that doesn't exist here, patched a `_sink` hook the emission
module didn't have, called `AggregatingCounter.inc()` (the method is
`add()`), and matched error text the helpers didn't produce. It
documented intent; it had never executed against this code.

### AI agent conversations

| Repo claim | Verdict | Evidence |
|---|---|---|
| Doc links (`/ai/monitoring/conversations/`, `…/ai-agents-module/`) | **Outdated** | Canonical pages are now CONV and PYAI. `/product/explore/conversations/` is a 404. |
| View is at "Explore → Conversations" | **Outdated** | CONV: "Explore → Agents"; Conversations is a tab there. |
| Span ops `gen_ai.invoke_agent` / `gen_ai.chat` / `gen_ai.execute_tool`, names `"<op> <subject>"` | **Correct** | PYAI, AISPEC. |
| `gen_ai.usage.input_tokens.cached`, `gen_ai.usage.output_tokens.reasoning` | **Outdated** | PYAI marks both deprecated → `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.reasoning.output_tokens`. |
| Cached / reasoning tokens are subsets of the totals | **Correct** | PYAI: "Cache and reasoning attributes are subsets of those totals". |
| Cost formula `(total − cached) × rate + cached × cached_rate` | **Unverifiable** as written | AISPEC only says under-reporting input tokens "produces negative costs" and that cost is derived at ingestion. |
| `sentry_sdk.ai` is "beta" | **Unverifiable** | No page labels it beta or GA, or gives a minimum version for `set_conversation_id`. |
| Derive the id from your session, not the trace id | **Correct** | PYAI: "omit it instead of deriving one from a trace or request ID." |
| `{role, parts}` messages, JSON-stringified; reasoning in a `reasoning` part | **Correct** | PYAI. |
| OpenAI Agents SDK (Python) and OpenAI SDK (Node) infer the id | **Correct** | CONV. |
| The `conversation=conversation.id` OpenAI Responses snippet sets the id | **Not re-verified** | Left as is. |
| (missing) minimum SDK for Conversations | **Gap** | PYAI: from 2.64.0 gen_ai spans are sent standalone, "required for Conversations". |
| (missing) manual attributes bypass PII options | **Gap** | PYAI: "The SDK doesn't filter attributes you set manually". |
| Never copy the conversation id into a metric tag "(unbounded cardinality)" | **Outdated** rationale | Still not a group-by tag. Allowed as declared context. |

## Revised model

The hypothesis going in was: split closed group-by dimensions from
high-cardinality debug context; keep naming, versioning and
one-meaning-per-metric; keep volume controls only if billing supports
them. **The sources confirm it, with one correction: context is not
free.** QUOTA says high-cardinality attributes inflate volume, so
context is declared per metric and kept small rather than opened up.

1. **Group-by tags (`tags=`)** — closed sets, enumerated or bucketed.
   Unchanged mechanics. Justification is alert and dashboard stability.
2. **Debug context (`context=`)** — declared key names with free
   values (ids). New. Validated to be a small primitive; free-text and
   personal-data keys and the SDK's `sentry.*` / `user.*` namespaces
   are refused. Not part of the metric's identity.
3. **Never on a metric** — free-form text, exception strings, emails,
   IPs, raw URLs. Unchanged.
4. **Naming, `.v2` versioning, `retired_at`, one meaning per metric,
   kind rules** — unchanged.
5. **Volume controls** — kept, because billing is per GB and Spike
   Protection excludes metrics. Sampling and the rate limiter are fixed
   so they do what the docs said. `before_send_metric` added.

## Decisions a maintainer should look at

- **Latency unit default is now `"millisecond"`.** `"ms"` still works
  via `unit="ms"`. Whether Sentry charts the two differently is not
  documented, and SEARCH shows `metric.unit` is part of what the metric
  selector matches on, so changing the unit of a live metric may split
  it. Existing registries should pass `unit="ms"` or migrate with a
  `.v2`.
- **Sampling is now uniform random**, replacing the tag-hash scheme.
  `count()`/`sum()` over a sampled distribution are under-reported;
  this is stated rather than papered over.
- **Rate-limit drops are reported once per window** as
  `instrumentation.rate_limit.drop_count`, no longer as one
  `instrumentation.violation.count` event per drop.
- **`instrumentation.violation.count`'s `rule` attribute is now a fixed
  code.** It used to be the full error message, which broke the skill's
  own rule about free-form strings.
- **The 200-character context cap and the forbidden-key list are this
  skill's policy.** Sentry documents no such limits.
- **Surface patterns** (`http_middleware.py`, `external_api_client.py`,
  `workflow_decorator.py`, `retry_loop.py`, `fallback_path.py`) don't
  yet thread `context=` through. The helpers they call accept it.
