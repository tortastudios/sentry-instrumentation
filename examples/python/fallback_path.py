"""Fallback / degradation helper — the drop-in pattern for tracking when the
system takes a degraded path.

Drop-in at `yourapp/observability_fallback.py` (or co-locate with the
emission module). The single-call helper `record_fallback(metric,
reason=...)` is the only approved way to emit a fallback counter.

Why a dedicated helper instead of `emit_counter`? Fallbacks are one of
the most common sources of ad-hoc, unreviewed metrics. Every
`record_fallback` call:

  1. Forces `reason` to be a keyword argument — no positional drift.
  2. Validates `reason` against the metric's `tag_constraints["reason"]`
     at call time — a typo raises in dev + tests, drops in prod.
  3. Carries the taxonomy inline: the `MetricDef` enumerates every
     allowed reason, so the reader of the registry sees the full
     degradation taxonomy without grepping call sites.

Usage:

    record_fallback(
        PRIMARY_SIGNAL_FALLBACK,
        reason="primary_empty",
        tags={"surface": "sidebar"},   # optional extra tags
    )

A fallback metric's `MetricDef` must declare `reason` in both
`allowed_tags` and `tag_constraints` with a closed enumerated set.
"""

from __future__ import annotations

from collections.abc import Mapping

from yourapp.observability import emit_counter
from yourapp.shared.metrics import MetricDef


def record_fallback(
    metric: MetricDef,
    *,
    reason: str,
    tags: Mapping[str, str] | None = None,
) -> None:
    """Emit a single fallback-path counter.

    `reason` is validated against `metric.tag_constraints["reason"]`;
    any additional `tags` must be in `metric.allowed_tags`.
    """

    if "reason" not in metric.allowed_tags:
        # Author mistake: a metric used with record_fallback must
        # declare reason. We raise here rather than drop, because this
        # is a registry error, not a runtime tag-value mismatch.
        raise ValueError(
            f"MetricDef {metric.name!r} is used with record_fallback but "
            f"does not declare 'reason' in allowed_tags."
        )

    merged: dict[str, str] = {"reason": reason}
    if tags:
        merged.update(tags)

    # emit_counter does the tag validation (reason value against
    # tag_constraints, extra keys against allowed_tags) so a bad
    # reason string surfaces the same way any other tag violation
    # does: raise in dev/tests, drop + violation counter in prod.
    emit_counter(metric, tags=merged)


# ---- Example MetricDef ----------------------------------------------------
#
#     PRIMARY_SIGNAL_FALLBACK = MetricDef.counter(
#         "primary_signal.fallback.count",
#         purpose="correctness",
#         owner="pipeline",
#         means=(
#             "Workflow took a fallback path because the primary data "
#             "signal was unavailable. reason enumerates which shape of "
#             "primary-signal failure triggered the fallback."
#         ),
#         tags={
#             "reason": frozenset({
#                 "primary_unavailable",
#                 "primary_empty",
#                 "primary_stale",
#                 "primary_invalid",
#             }),
#             "surface": frozenset({"sidebar", "inline", "api"}),
#         },
#         emit_frequency="per_event",
#         loop_policy="aggregate_only",
#     )


__all__ = ["record_fallback"]
