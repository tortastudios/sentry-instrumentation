"""Sentry init + validating emission helpers + loop-safe aggregators.

Drop-in at `yourapp/observability.py`. This module is the only place
that calls `sentry_sdk.metrics.*` directly — every other module emits
through the validating helpers below.

Tested against `sentry-sdk==2.75.0`. Sentry's Python docs give 2.44.0
as the minimum version for `sentry_sdk.metrics`
(https://docs.sentry.io/platforms/python/metrics/).

The integrations shown in `init_sentry` (`FastApiIntegration`,
`StarletteIntegration`, `AnthropicIntegration`) reflect one
deployment's stack. Swap them for the integrations your app uses
(e.g., `DjangoIntegration`, `FlaskIntegration`, `CeleryIntegration`)
or drop them entirely. Only the validating helpers + aggregators are
the load-bearing part of this module.

Contracts enforced:
- Every helper's first argument is a `MetricDef`. Raw strings,
  f-strings, and variables fail a type check.
- `tags=` are group-by dimensions: keys must be in
  `metric.allowed_tags`; values must be in the enumerated set or
  produced by the bucket function named in `metric.tag_constraints`.
- `context=` are debug-context attributes: keys must be declared in
  `metric.context_attributes`; values are free but must be a
  str/int/float/bool, and strings are capped at
  `MAX_CONTEXT_VALUE_CHARS`.
- `emit_latency` checks the metric's unit is a millisecond unit.
- `emit_failure` requires a `FailureClass` value and validates it
  against the metric's `failure_class` constraint.

Both `tags` and `context` are sent to Sentry in the same `attributes`
dict. The split is this skill's governance, not a Sentry concept.

Fail-safe behavior:
- In production (`settings.environment == "production"` and pytest
  not loaded), every helper catches exceptions from the SDK and
  validation errors, drops the emission, and increments
  `instrumentation.violation.count`.
- In pytest or non-production, validation errors raise
  `InstrumentationContractError` so tests fail fast.
"""

from __future__ import annotations

import contextlib
import logging
import random
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import sentry_sdk

from yourapp.config import Settings
from yourapp.shared import metric_tags
from yourapp.shared.failure_taxonomy import FailureClass
from yourapp.shared.metrics import LATENCY_UNITS, MetricDef

logger = logging.getLogger(__name__)

ContextValue = str | int | float | bool

# Cap on a single context string. This skill's own limit, chosen to keep
# ids in and free-form text out; Sentry documents no attribute size limit.
MAX_CONTEXT_VALUE_CHARS = 200

# Metric names dropped in `before_send_metric`. Sentry's quota docs call
# SDK-side filtering "the most effective way to reduce your Application
# Metrics quota usage":
# https://docs.sentry.io/pricing/quotas/manage-application-metrics-quota/
DROPPED_METRIC_NAMES: frozenset[str] = frozenset()


class InstrumentationContractError(Exception):
    """Raised in pytest + non-production when an emit helper is misused.

    `rule` is a short fixed code. It is what gets attached to
    `instrumentation.violation.count`, so the violation counter groups
    by a closed set instead of by error-message text.
    """

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule


def _before_send_metric(metric: Any, _hint: Any) -> Any:
    """Drop metrics listed in `DROPPED_METRIC_NAMES` before they are sent."""

    if metric.get("name") in DROPPED_METRIC_NAMES:
        return None
    return metric


def init_sentry(settings: Settings) -> None:
    """Initialize Sentry with tracing + profiling + AI monitoring + Logs.

    Metrics need no option: they are on by default once the SDK is
    initialized. The SDK attaches `sentry.environment`,
    `sentry.release`, `sentry.sdk.*` and `server.address` to every
    metric. It attaches `user.id` / `user.name` / `user.email` only
    when a user is set on the scope AND user-info collection is on
    (`send_default_pii=True`, or `data_collection={"user_info": True}`);
    both are off here by default.

    Detecting pytest in `sys.modules` is a surgical gate: tests
    transitively import the app, whose module body initializes Sentry.
    A local `.env` with a real `SENTRY_DSN` would route every test
    exception to the real project. `conftest` can't undo this cleanly
    because `get_settings()` is `lru_cache`d and `init_sentry` has
    already run by fixture time.
    """

    if "pytest" in sys.modules:
        return
    if not settings.sentry_dsn:
        return

    # Imported here so this module loads without the optional
    # framework packages installed.
    from sentry_sdk.integrations.anthropic import AnthropicIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            AnthropicIntegration(),
        ],
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        enable_logs=True,
        before_send_metric=_before_send_metric,
    )


# ---- The one place that touches the SDK ------------------------------------


def _sink(
    kind: str,
    *,
    name: str,
    value: float,
    unit: str | None,
    attributes: dict[str, ContextValue],
) -> None:
    """Send one metric event. Tests monkeypatch this to capture output."""

    if kind == "counter":
        sentry_sdk.metrics.count(name, value, unit=unit, attributes=attributes)
    elif kind == "gauge":
        sentry_sdk.metrics.gauge(name, value, unit=unit, attributes=attributes)
    else:
        sentry_sdk.metrics.distribution(
            name, value, unit=unit, attributes=attributes
        )


def _safe_sink(
    kind: str,
    name: str,
    value: float,
    unit: str | None,
    attributes: dict[str, ContextValue],
) -> None:
    try:
        _sink(kind, name=name, value=value, unit=unit, attributes=attributes)
    except Exception:  # noqa: BLE001 — observability never raises
        return


# ---- Validation core -------------------------------------------------------


def _is_strict_environment() -> bool:
    """Strict mode = pytest loaded, or non-production. Raises on misuse."""

    if "pytest" in sys.modules:
        return True
    settings = _settings_for_validation()
    if settings is None:
        return False
    return settings.environment != "production"


def _settings_for_validation() -> Settings | None:
    """Lazily resolve `Settings` so helpers work before app startup."""

    try:
        from yourapp.config import get_settings
        return get_settings()
    except Exception:  # noqa: BLE001 — observability never raises
        return None


def _record_violation(metric_name: str, rule: str) -> None:
    """Emit the `correctness` counter that tracks validation drops.

    Both attributes are closed sets: `metric` is a registry name and
    `rule` is an `InstrumentationContractError.rule` code.
    """

    _safe_sink(
        "counter",
        "instrumentation.violation.count",
        1.0,
        None,
        {"metric": metric_name, "rule": rule},
    )


def _validate_tags(
    metric: MetricDef,
    tags: Mapping[str, str] | None,
    *,
    bucket_registry: Mapping[str, Callable[..., str]],
) -> None:
    """Check group-by tag keys + values against the metric's contract."""

    if "failure_class" in metric.allowed_tags and "failure_class" not in (tags or {}):
        raise InstrumentationContractError(
            "failure_class_missing",
            f"metric {metric.name!r}: failure_class tag is required; "
            f"emit through emit_failure(...)",
        )
    if not tags:
        return
    for key, value in tags.items():
        if key not in metric.allowed_tags:
            raise InstrumentationContractError(
                "unknown_tag_key",
                f"metric {metric.name!r}: unknown tag key {key!r} "
                f"(not in allowed_tags)",
            )
        constraint = metric.tag_constraints.get(key)
        if isinstance(constraint, frozenset):
            if value not in constraint:
                raise InstrumentationContractError(
                    "tag_value_outside_constraints",
                    f"metric {metric.name!r}: tag value {key}={value!r} "
                    f"outside enumerated constraint",
                )
        elif isinstance(constraint, str):
            # Bucket function name — enforcement is that the emitter
            # called the bucket. We can't check from here without a
            # redundant call; review covers this.
            if constraint not in bucket_registry:
                raise InstrumentationContractError(
                    "unknown_bucket_function",
                    f"metric {metric.name!r}: unknown bucket function "
                    f"{constraint!r} for tag {key!r}",
                )


def _validate_context(
    metric: MetricDef, context: Mapping[str, ContextValue] | None
) -> None:
    """Check debug-context keys are declared and values are small primitives."""

    if not context:
        return
    for key, value in context.items():
        if key not in metric.context_attributes:
            raise InstrumentationContractError(
                "unknown_context_key",
                f"metric {metric.name!r}: context key {key!r} is not declared "
                f"in context=",
            )
        if not isinstance(value, (str, int, float, bool)):
            raise InstrumentationContractError(
                "context_value_invalid",
                f"metric {metric.name!r}: context {key!r} must be a "
                f"str/int/float/bool, got {type(value).__name__}",
            )
        if isinstance(value, str) and len(value) > MAX_CONTEXT_VALUE_CHARS:
            raise InstrumentationContractError(
                "context_value_invalid",
                f"metric {metric.name!r}: context {key!r} is longer than "
                f"{MAX_CONTEXT_VALUE_CHARS} characters — ids only, no free text",
            )


def _guard_kind(metric: MetricDef, expected: str) -> None:
    if metric.kind != expected:
        raise InstrumentationContractError(
            "wrong_kind",
            f"metric {metric.name!r}: kind={metric.kind!r}, expected {expected!r}",
        )


# ---- Rate limiter ----------------------------------------------------------
#
# Sentry bills Application Metrics by data volume, and Spike Protection
# does not cover metrics, so a client-side cap is the only burst guard.
# Drops are counted locally and reported as ONE event per window —
# reporting each drop as its own event would send as much as it saved.

# name -> (window_start, emitted_in_window, dropped_in_window)
_rate_buckets: dict[str, tuple[float, float, float]] = {}


def _should_drop_for_rate_limit(metric: MetricDef) -> bool:
    if metric.max_rate_hz is None:
        return False
    now = time.monotonic()
    window_start, count, dropped = _rate_buckets.get(metric.name, (now, 0.0, 0.0))
    if now - window_start >= 1.0:
        _flush_rate_limit_drops(metric.name, dropped)
        window_start, count, dropped = now, 0.0, 0.0
    count += 1.0
    drop = count > metric.max_rate_hz
    if drop:
        dropped += 1.0
    _rate_buckets[metric.name] = (window_start, count, dropped)
    return drop


def _flush_rate_limit_drops(metric_name: str, dropped: float) -> None:
    if dropped > 0:
        _safe_sink(
            "counter",
            "instrumentation.rate_limit.drop_count",
            dropped,
            None,
            {"metric": metric_name},
        )


def flush_rate_limit_drops() -> None:
    """Report pending drop counts now (call at shutdown, and from tests)."""

    for name, (window_start, count, dropped) in list(_rate_buckets.items()):
        _flush_rate_limit_drops(name, dropped)
        _rate_buckets[name] = (window_start, count, 0.0)


# ---- Sampling --------------------------------------------------------------
#
# Uniform random sampling per emission. Every tag combination keeps
# roughly `sampling_rate` of its samples, so percentiles stay
# representative. `count()` / `sum()` / rates over a sampled metric are
# under-reported by that factor — the Python SDK has no public way to
# attach a sample weight — so derive volumes from the paired counter.

_rng = random.Random()


def _should_drop_for_sampling(metric: MetricDef) -> bool:
    if metric.sampling_rate >= 1.0:
        return False
    return _rng.random() >= metric.sampling_rate


# ---- Public emit helpers ---------------------------------------------------


# Bucket-function registry. Pre-loaded with the approved buckets from
# `metric_tags`; projects add their own with `register_bucket`.
_BUCKET_REGISTRY: dict[str, Callable[..., str]] = {
    name: getattr(metric_tags, name) for name in metric_tags.__all__
}


def register_bucket(name: str, fn: Callable[..., str]) -> None:
    _BUCKET_REGISTRY[name] = fn


def _emit(
    kind: str,
    metric: MetricDef,
    value: float,
    tags: Mapping[str, str] | None,
    context: Mapping[str, ContextValue] | None,
    *,
    sample: bool = False,
    rate_limit: bool = True,
) -> None:
    try:
        _guard_kind(metric, kind)
        _validate_tags(metric, tags, bucket_registry=_BUCKET_REGISTRY)
        _validate_context(metric, context)
    except InstrumentationContractError as err:
        if _is_strict_environment():
            raise
        _record_violation(metric.name, err.rule)
        return

    if sample and _should_drop_for_sampling(metric):
        return
    if rate_limit and _should_drop_for_rate_limit(metric):
        return

    attributes: dict[str, ContextValue] = {**(tags or {}), **(context or {})}
    _safe_sink(kind, metric.name, value, metric.unit, attributes)


def emit_counter(
    metric: MetricDef,
    *,
    tags: Mapping[str, str] | None = None,
    context: Mapping[str, ContextValue] | None = None,
    value: float = 1.0,
) -> None:
    """Record a Sentry counter. Validates against the MetricDef."""

    _emit("counter", metric, value, tags, context)


def emit_gauge(
    metric: MetricDef,
    *,
    tags: Mapping[str, str] | None = None,
    context: Mapping[str, ContextValue] | None = None,
    value: float,
) -> None:
    """Record a Sentry gauge. Validates against the MetricDef."""

    _emit("gauge", metric, value, tags, context, rate_limit=False)


def emit_distribution(
    metric: MetricDef,
    *,
    tags: Mapping[str, str] | None = None,
    context: Mapping[str, ContextValue] | None = None,
    value: float,
) -> None:
    """Record a Sentry distribution. Validates kind + samples + rate-limits."""

    _emit("distribution", metric, value, tags, context, sample=True)


def emit_latency(
    metric: MetricDef,
    *,
    duration_ms: float,
    tags: Mapping[str, str] | None = None,
    context: Mapping[str, ContextValue] | None = None,
) -> None:
    """Typed distribution helper — the metric's unit must be milliseconds."""

    if metric.unit not in LATENCY_UNITS:
        if _is_strict_environment():
            raise InstrumentationContractError(
                "latency_unit",
                f"emit_latency requires a millisecond unit "
                f"({sorted(LATENCY_UNITS)}), got {metric.unit!r} "
                f"for {metric.name!r}",
            )
        _record_violation(metric.name, "latency_unit")
        return
    emit_distribution(metric, value=duration_ms, tags=tags, context=context)


def emit_failure(
    metric: MetricDef,
    *,
    failure: FailureClass,
    tags: Mapping[str, str] | None = None,
    context: Mapping[str, ContextValue] | None = None,
) -> None:
    """Failure counter — injects the `failure_class` tag."""

    if "failure_class" not in metric.allowed_tags:
        if _is_strict_environment():
            raise InstrumentationContractError(
                "failure_without_failure_class_tag",
                f"emit_failure requires a failure_class-tagged metric; "
                f"got {metric.name!r} with allowed_tags={metric.allowed_tags}",
            )
        _record_violation(metric.name, "failure_without_failure_class_tag")
        return
    full_tags: dict[str, str] = {"failure_class": failure.value}
    if tags:
        full_tags.update(tags)
    emit_counter(metric, tags=full_tags, context=context)


@contextlib.contextmanager
def time_latency(
    metric: MetricDef,
    *,
    tags: Mapping[str, str] | None = None,
    context: Mapping[str, ContextValue] | None = None,
) -> Iterator[None]:
    """Context manager — record start→stop latency as a one-liner."""

    started = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        emit_latency(metric, duration_ms=elapsed_ms, tags=tags, context=context)


# ---- Loop-safe aggregators -------------------------------------------------


class AggregatingCounter:
    """Counter accumulator — emits once on __exit__.

    Only approved way to emit a counter inside a loop when the
    metric's `loop_policy != "allowed"`. One event carrying the total
    gives the same `sum()` as N events for a fraction of the volume.
    The trade-off: the single event links to one trace/span, not N.
    """

    def __init__(
        self,
        metric: MetricDef,
        *,
        tags: Mapping[str, str] | None = None,
        context: Mapping[str, ContextValue] | None = None,
    ) -> None:
        self.metric = metric
        self.tags = dict(tags or {})
        self.context = dict(context or {})
        self._total = 0.0

    def add(self, value: float = 1.0) -> None:
        self._total += value

    def __enter__(self) -> AggregatingCounter:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self._total > 0:
            emit_counter(
                self.metric, tags=self.tags, context=self.context, value=self._total
            )


class DurationAccumulator:
    """Duration accumulator — emits a single distribution sample on exit.

    The emitted value is the *total* time accumulated across
    iterations, not per-iteration samples. For per-iteration
    percentiles set `loop_policy="allowed"` on the metric.
    """

    def __init__(
        self,
        metric: MetricDef,
        *,
        tags: Mapping[str, str] | None = None,
        context: Mapping[str, ContextValue] | None = None,
    ) -> None:
        self.metric = metric
        self.tags = dict(tags or {})
        self.context = dict(context or {})
        self._total_ms = 0.0

    def add_ms(self, value: float) -> None:
        self._total_ms += value

    def __enter__(self) -> DurationAccumulator:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self._total_ms > 0:
            emit_latency(
                self.metric,
                duration_ms=self._total_ms,
                tags=self.tags,
                context=self.context,
            )


__all__ = [
    "AggregatingCounter",
    "DurationAccumulator",
    "InstrumentationContractError",
    "emit_counter",
    "emit_distribution",
    "emit_failure",
    "emit_gauge",
    "emit_latency",
    "flush_rate_limit_drops",
    "init_sentry",
    "register_bucket",
    "time_latency",
]
