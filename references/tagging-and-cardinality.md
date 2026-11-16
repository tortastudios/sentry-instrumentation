# Attributes: group-by tags and debug context

Sentry's Application Metrics stores every emission as a full event with
its attributes intact. It is not a pre-aggregated time-series store, so
a new attribute value does **not** create a new billable series. Sentry
says so directly: "High cardinality is the default, not a limit"
([product page](https://sentry.io/product/metrics/)) and "Sentry's
Application Metrics stores full events, including high-cardinality
fields like user"
([launch post](https://blog.sentry.io/introducing-application-metrics/)).

So this skill no longer bans high-cardinality attributes. It separates
two jobs an attribute can do, and governs them differently:

| | Group-by tags (`tags=`) | Debug context (`context=`) |
|---|---|---|
| Job | The dimensions dashboards and alert rules group and filter on | Find the affected customer / request after a spike |
| Values | Closed set: enumerated, or the output of a bucket function | Free, but a small primitive (an id, not text) |
| Examples | `failure_class`, `outcome`, `stage`, `status_class`, `provider` | `account_id`, `project_id`, `order_id`, `replay_id`, `conversation_id` |
| Declared as | `tags={"key": frozenset({...}) \| "bucket_fn"}` | `context={"key", ...}` |
| Part of metric identity | Yes — changing them needs a `.v2` | No — add or remove freely |

Both are sent to Sentry in the same `attributes` dict. The split is this
skill's governance, not a Sentry concept.

```python
CHECKOUT_FAILED = MetricDef.failure_counter(
    "checkout.payment.failure.count",
    owner="payments",
    means="A payment attempt failed after retries.",
    tags={"provider": frozenset({"stripe", "adyen"})},   # group / alert on these
    context={"account_id", "order_id"},                  # look these up when it spikes
    emit_frequency="per_event",
)

emit_failure(
    CHECKOUT_FAILED,
    failure=classify(exc),
    tags={"provider": "stripe"},
    context={"account_id": account.id, "order_id": order.id},
)
```

## Why group-by tags stay closed

Not because of cost per series — there isn't one. The reasons that
still hold:

- **Alert rules and dashboards need stable values.** A monitor can
  match `failure_class:timeout`. It can't match
  `AttributeError: 'NoneType' object has no attribute 'id'`, and a
  group-by on a free-form field yields one row per string.
- **A closed set is a contract.** Reviewers and the CI gate can check
  that a call site uses a declared key and a declared value. Nobody can
  check a free string.
- **Sentry's own guidance.** Its quota docs say to "pair [high-
  cardinality attributes] with bounded attributes like environment,
  region, or plan tier"
  ([quota guide](https://docs.sentry.io/pricing/quotas/manage-application-metrics-quota/)).

One naming rule follows from the same model: a dimension belongs in an
attribute, never in the metric name. Sentry's cookbook lists
`schedule.event.success` / `schedule.event.duplicate` as a pitfall —
use one metric with a `result` tag
([cookbook](https://sentry.io/cookbook/custom-metrics-dashboard-alerts-nextjs/)).

## What context costs

Sentry bills Application Metrics by data volume: 5 GB included on every
plan, then $0.50/GB from the pay-as-you-go budget
([pricing](https://docs.sentry.io/pricing/)). A metric event is billed
as the event "including metadata like name, kind, value, trace_id,
span_id, and custom attributes"
([quota guide](https://docs.sentry.io/pricing/quotas/manage-application-metrics-quota/)).

The same guide says: "High-cardinality custom attributes (user IDs,
request IDs, free-form strings) inflate metric volume", and to keep only
the most valuable ones. Sentry's cookbook says the opposite in
passing ("adding more attributes costs nothing"). The two pages
disagree; this skill follows the quota guide, since it is the billing
document. Sentry does not publish how many bytes an attribute adds, so
treat each context key as a small per-event cost, not a free one:

- Declare the two or three ids you would actually search by.
- Keep values short. The helpers reject context strings longer than
  200 characters (`MAX_CONTEXT_VALUE_CHARS` — this skill's limit, not
  Sentry's; Sentry documents no attribute size limit).

## Never on a metric, as a tag or as context

These are banned for privacy and payload size, whatever Sentry's storage
can handle:

- **Free-form text:** prompt text, LLM output, message bodies, anything
  a user typed.
- **Exception data:** `str(exc)`, `repr(exc)`, stack frames,
  `type(exc).__name__`. Use `classify(exc)` → `FailureClass`.
- **Direct personal data:** email addresses, IP addresses, user agents.
- **Raw URLs and query strings.** Use the route template
  (`/users/{id}`) as a tag.
- **Timestamps and file paths.**

`MetricDef` refuses to declare the obvious offenders as context keys
(`email`, `prompt`, `error_message`, `url`, … — see
`FORBIDDEN_CONTEXT_KEYS` in `examples/python/metric_def.py`).

## What you don't need to add

- **`trace_id` / `span_id`.** Every metric event already carries them;
  that is how you jump from a spike to the trace
  ([product docs](https://docs.sentry.io/product/explore/metrics/)).
  Don't add `trace_id` or `request_id` as context to get that link.
- **Environment, release, SDK, server.** The SDK attaches
  `sentry.environment`, `sentry.release`, `sentry.sdk.name`,
  `sentry.sdk.version` and `server.address` to every metric
  ([Python docs](https://docs.sentry.io/platforms/python/metrics/)).
- **The user.** Call `sentry_sdk.set_user({"id": ...})` once per
  request. The SDK then attaches `user.id`, `user.name` and
  `user.email` to metrics — but only when user-info collection is
  enabled (`send_default_pii=True`, or
  `data_collection={"user_info": True}` on newer SDKs). With it off
  (the default) no `user.*` attribute is sent. `sentry.*` and `user.*`
  are reserved: `MetricDef` won't let you declare them as context.

  If you turn user-info collection on, `user.email` rides along on
  every metric event. Decide that deliberately.

## Approved tag value shapes

Exactly two shapes are allowed for `tags=`:

### Enumerated strings

List every allowed value explicitly in `MetricDef.tag_constraints`:

```python
tags={"cache_status": frozenset({"hit", "miss", "skipped", "error"})}
```

### Approved bucket functions

The bucket functions live in `yourapp/shared/metric_tags.py`. Each
is total (never raises), returns a string from a small finite set,
and is documented in `examples/python/metric_tags.py`.

| Function | Returns | Use for |
|---|---|---|
| `status_code_class(code)` | `"1xx" \| "2xx" \| "3xx" \| "4xx" \| "5xx" \| "other"` | HTTP response status |
| `size_bucket(num_bytes)` | `"0_1kb" \| "1_10kb" \| "10_100kb" \| "100kb_1mb" \| "1mb_plus"` | payload sizes |
| `count_bucket(n)` | `"0" \| "1-9" \| "10-49" \| "50+"` | collection sizes, result counts |
| `attempt_bucket(n)` | `"1" \| "2" \| "3-5" \| "6+"` | retry-loop attempt indices |
| `bool_tag(b)` | `"true" \| "false"` | boolean-valued tags |

Call sites pass the raw value through the bucket at emission time:

```python
emit_counter(
    API_REQUEST_COUNT,
    tags={"status_class": status_code_class(response.status_code)},
)
```

The `MetricDef.tag_constraints` entry for that key stores either the
full enumerated set, or the string name of the bucket function. The
validator resolves both shapes.

Dated model/version strings (`"claude-opus-4-6-20251001"`) are a common
way for a tag to stop being a closed set: the enumeration goes stale
every release. Strip the date, or move the full string to `context=`.

## Cardinality classes (group-by tags only)

`cardinality` describes how many rows a group-by on the metric's tags
produces. It is a readability budget, not a billing one.

### `low` (default)

- ≤ 20 distinct tag combinations in practice.
- No justification required.

### `medium`

- ≤ ~200 distinct tag combinations.
- Requires `cardinality="medium"` on the `MetricDef` **and** a
  `Justification:` sentence in `means=` saying which dashboard or alert
  needs that many groups. The CI gate checks for it (M006).

### Anything larger

Not a group-by tag. If the value is an id, declare it as `context=`.
If it is text, it belongs on a span or a log line.

## Adding a new bucket function

Bucket functions are a controlled vocabulary — adding one is a
deliberate change, not a one-off convenience:

1. The new bucket resolves an otherwise-unbounded input (e.g.,
   floats, durations, external-service response codes) into ≤ ~10
   values.
2. It's documented in `yourapp/shared/metric_tags.py` (or the
   language's equivalent module) with its enumeration spelled out in
   the docstring, and registered with `register_bucket(...)`.
3. It's referenced from this file (`tagging-and-cardinality.md`) in a
   follow-up PR so the skill stays accurate.

## Anti-patterns

Caught by the CI gate when the call uses a dict literal and a
module-level metric symbol:

1. `tags={"account_id": account.id}` — an id used as a group-by tag.
   Undeclared tag key → M007. Declare it as `context=` instead.
2. `context={"session_id": s.id}` on a metric that doesn't declare
   `session_id` → M014.
3. `context={"email", ...}` or `context={"user.id"}` in a `MetricDef`
   → M014 (forbidden / reserved key).

Caught by the runtime validator (raises in tests and non-production,
drops and counts in production):

4. A tag value outside the enumeration in `tag_constraints`.
5. A context value that isn't a str/int/float/bool, or a string over
   200 characters.

Caught in review only:

6. `tags={"route": request.url.path}` — raw path instead of the route
   template.
7. `tags={"error": str(exc)}` when `error` was declared with a bucket
   function name — the validator can't prove the bucket was called.
