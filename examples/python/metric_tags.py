"""Approved bucket functions for low-cardinality metric tag values.

Drop-in at `yourapp/shared/metric_tags.py`. Every tag value passed to
an `emit_*` helper must be either enumerated verbatim in
`MetricDef.tag_constraints` or the output of one of these functions.

Each bucket is *total* — never raises on pathological inputs, always
returns a string from the small finite set documented in its
docstring. The CI gate keys tag validation off those enumerations.

Adding a new bucket is a deliberate change: pick boundaries so the
total set stays ≤ ~10 values, document the trade-off in the
function's docstring, and reference it from
`references/tagging-and-cardinality.md`.
"""

from __future__ import annotations


def status_code_class(code: int) -> str:
    """Map an HTTP status code to its class string.

    Returns `"1xx" | "2xx" | "3xx" | "4xx" | "5xx" | "other"`. The
    `"other"` bucket catches codes outside 100-599 so the function is
    total.
    """

    if 100 <= code < 200:
        return "1xx"
    if 200 <= code < 300:
        return "2xx"
    if 300 <= code < 400:
        return "3xx"
    if 400 <= code < 500:
        return "4xx"
    if 500 <= code < 600:
        return "5xx"
    return "other"


def size_bucket(num_bytes: int) -> str:
    """Bucket a byte count into an order-of-magnitude label.

    Returns one of `"0_1kb" | "1_10kb" | "10_100kb" | "100kb_1mb" | "1mb_plus"`.
    Negative inputs collapse into `"0_1kb"` so the function stays
    total. Boundaries are powers of ten because payload regressions
    show up as order-of-magnitude jumps, not KB-scale drift.
    """

    if num_bytes < 1_024:
        return "0_1kb"
    if num_bytes < 10 * 1_024:
        return "1_10kb"
    if num_bytes < 100 * 1_024:
        return "10_100kb"
    if num_bytes < 1_024 * 1_024:
        return "100kb_1mb"
    return "1mb_plus"


def count_bucket(n: int) -> str:
    """Bucket an integer count into `"0" | "1-9" | "10-49" | "50+"`.

    Four buckets is deliberately coarse — the questions we ask of
    count tags ("did we get anything", "did we get the rough
    expected order") don't need finer resolution.
    """

    if n <= 0:
        return "0"
    if n < 10:
        return "1-9"
    if n < 50:
        return "10-49"
    return "50+"


def attempt_bucket(n: int) -> str:
    """Bucket a retry-attempt index into `"1" | "2" | "3-5" | "6+"`.

    Retry logic typically has a small max budget (2-3 attempts) so
    the first two buckets are single-valued; `"3-5"` catches
    unusually persistent retries and `"6+"` catches runaway loops
    worth an alert. Zero/negative inputs normalize to `"1"` so call
    sites can pass `attempt_idx + 1` or `attempt_idx`
    interchangeably.
    """

    if n <= 1:
        return "1"
    if n == 2:
        return "2"
    if n <= 5:
        return "3-5"
    return "6+"


def bool_tag(value: bool) -> str:
    """Render a boolean as the canonical tag string.

    Pins the exact casing every metric agrees on — a `"True"`/`"true"`
    split would double the series count for the affected tag.
    """

    return "true" if value else "false"


__all__ = [
    "attempt_bucket",
    "bool_tag",
    "count_bucket",
    "size_bucket",
    "status_code_class",
]
