# Tagging and cardinality policy

Sentry charges (directly in ingest + indirectly in alert-rule
matchability) for every distinct tag tuple. A single unbounded tag
blows up the series count, pollutes dashboards with per-user noise,
and leaks PII through what looked like a harmless label.

## Forbidden tag keys and values

Never use as either a tag key or a tag value:

- User/entity ids: `user_id`, `creator_id`, `run_id`, `request_id`,
  `trace_id`, `session_id`, `account_id`.
- URL-level data: URL path parameters, the raw URL, query strings.
- Freeform strings: prompt text, LLM output, any field that could
  contain user-typed content.
- Exception data: `str(exception)`, `repr(exception)`, stack frames,
  `type(exc).__name__` (use `FailureClass.classify()` instead).
- Dated model/version strings: major versions like
  `"claude-opus-4-6"` or `"gpt-4"` are fine as a closed enumeration,
  but `"claude-opus-4-6-20251001"` or `"model-v2-20260401"` is not —
  date-suffixed versions inflate the series count every release.
  Strip the date (or use a bucket function) before tagging.
- Timestamps, file paths, IP addresses.

The CI gate greps for these literals in `tag_constraints` and call
sites.

## Approved tag value shapes

Exactly two shapes allowed:

### Enumerated strings

List every allowed value explicitly in
`MetricDef.tag_constraints`:

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

## Cardinality classes

### `low` (default)

- ≤ 20 distinct tag combinations in practice.
- No justification required.
- Every tag value is enumerated or bucketed.

### `medium`

- ≤ ~200 distinct tag combinations.
- Requires `cardinality="medium"` on the `MetricDef` **and** a
  justification paragraph in `means=` explaining why the dimensional
  explosion is worth paying for.
- Reviewer red flag; CI gate requires the justification.

### `high`

- Forbidden by the charter. If you think you need high-cardinality
  tags, you probably want a log line (routed to Sentry via the
  `LoggingIntegration`) or a trace span (via `sentry_sdk.trace(...)`),
  not a metric.

## Adding a new bucket function

Bucket functions are a controlled vocabulary — adding one is a
deliberate change, not a one-off convenience:

1. The new bucket resolves an otherwise-unbounded input (e.g.,
   floats, durations, external-service response codes) into ≤ ~10
   values.
2. It's documented in `yourapp/shared/metric_tags.py` (or the
   language's equivalent module) with its enumeration spelled out in
   the docstring.
3. It's referenced from this file (`tagging-and-cardinality.md`) in a
   follow-up PR so the skill stays accurate.

## Anti-patterns caught by the CI gate

1. `tags={"user_id": auth.user_id}` — forbidden key.
2. `tags={"route": request.url.path}` — raw URL path.
3. `tags={"error": str(exc)}` — raw exception string.
4. `tags={"model": f"modelname-{date_suffix}"}` — unbounded string.
5. A tag key in the emission that isn't in `MetricDef.allowed_tags`.
6. A tag value outside the enumeration in `tag_constraints` (if
   enumerated) or not produced by the referenced bucket function (if
   bucket-function-constrained).
