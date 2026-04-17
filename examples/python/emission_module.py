"""Sentry init + validating emission helpers + loop-safe aggregators.

Drop-in at `yourapp/observability.py`. This module is the only place
that calls `sentry_sdk.metrics.*` directly — every other module emits
through the validating helpers below.

The integrations shown in `init_sentry` (`FastApiIntegration`,
`StarletteIntegration`, `AnthropicIntegration`) reflect one
deployment's stack. Swap them for the integrations your app uses
(e.g., `DjangoIntegration`, `FlaskIntegration`, `CeleryIntegration`)
or drop them entirely. Only the validating helpers + aggregators are
the load-bearing part of this module.

Contracts enforced:
- Every helper's first argument is a `MetricDef`. Raw strings,
  f-strings, and variables fail a type check.
- Tag keys must be in `metric.allowed_tags`; tag values must be in
  the enumerated set or produced by the bucket function named in
  `metric.tag_constraints`.
- `emit_latency` checks `metric.unit == "ms"`.
- `emit_failure` requires a `FailureClass` value and validates it
  against the metric's `failure_class` constraint.

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
import hashlib
import logging
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.anthropic import AnthropicIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from yourapp.config import Settings
from yourapp.shared.failure_taxonomy import FailureClass
from yourapp.shared.metrics import MetricDef

logger = logging.getLogger(__name__)


class InstrumentationContractError(Exception):
    """Raised in pytest + non-production when an emit helper is misused."""


def init_sentry(settings: Settings) -> None:
    """Initialize Sentry with tracing + profiling + AI monitoring + Logs.

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
        send_default_pii=False,
        _experiments={"enable_logs": True},
    )


# ---- Validation core -------------------------------------------------------


def _is_strict_environment(settings: Settings | None) -> bool:
    """Strict mode = pytest loaded, or non-production. Raises on misuse."""

    if "pytest" in sys.modules:
        return True
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
    """Emit the `correctness` counter that tracks validation drops."""

    try:
        sentry_sdk.metrics.count(
            name="instrumentation.violation.count",
            value=1.0,
            attributes={"metric": metric_name, "rule": rule},
        )
    except Exception:  # noqa: BLE001
        return


def _validate_tags(
    metric: MetricDef,
    tags: Mapping[str, str] | None,
    *,
    bucket_registry: Mapping[str, Callable[..., str]],
) -> None:
    """Check tag keys + values against the metric's contract."""

    if not tags:
        return
    for key, value in tags.items():
        if key not in metric.allowed_tags:
            raise InstrumentationContractError(
                f"metric {metric.name!r}: tag key {key!r} not in allowed_tags"
            )
        constraint = metric.tag_constraints.get(key)
        if isinstance(constraint, frozenset):
            if value not in constraint:
                raise InstrumentationContractError(
                    f"metric {metric.name!r}: tag {key}={value!r} "
                    f"outside enumerated constraint"
                )
        elif isinstance(constraint, str):
            # Bucket function name — enforcement is that the emitter
            # called the bucket. We can't check from here without a
            # redundant call; the CI gate covers this statically.
            if constraint not in bucket_registry:
                raise InstrumentationContractError(
                    f"metric {metric.name!r}: unknown bucket function "
                    f"{constraint!r} for tag {key!r}"
                )


def _guard_kind(metric: MetricDef, expected: str) -> None:
    if metric.kind != expected:
        raise InstrumentationContractError(
            f"metric {metric.name!r}: kind={metric.kind!r}, expected {expected!r}"
        )


# ---- Rate limiter ----------------------------------------------------------


_rate_buckets: dict[str, tuple[float, float]] = {}  # name -> (window_start, count)


def _should_drop_for_rate_limit(metric: MetricDef) -> bool:
    if metric.max_rate_hz is None:
        return False
    now = time.monotonic()
    window_start, count = _rate_buckets.get(metric.name, (now, 0.0))
    if now - window_start >= 1.0:
        window_start, count = now, 0.0
    count += 1.0
    _rate_buckets[metric.name] = (window_start, count)
    return count > metric.max_rate_hz


# ---- Sampling --------------------------------------------------------------


def _should_drop_for_sampling(
    metric: MetricDef, tags: Mapping[str, str] | None
) -> bool:
    if metric.sampling_rate >= 1.0:
        return False
    digest = hashlib.sha256(
        (metric.name + "|" + _tag_key(tags)).encode("utf-8")
    ).digest()
    bucket = int.from_bytes(digest[:4], "big") / 2**32
    return bucket >= metric.sampling_rate


def _tag_key(tags: Mapping[str, str] | None) -> str:
    if not tags:
        return ""
    return "&".join(f"{k}={v}" for k, v in sorted(tags.items()))


# ---- Public emit helpers ---------------------------------------------------


# Bucket-function registry — projects populate on import.
_BUCKET_REGISTRY: dict[str, Callable[..., str]] = {}


def register_bucket(name: str, fn: Callable[..., str]) -> None:
    _BUCKET_REGISTRY[name] = fn


def emit_counter(
    metric: MetricDef,
    *,
    tags: Mapping[str, str] | None = None,
    value: float = 1.0,
) -> None:
    """Record a Sentry counter. Validates against the MetricDef."""

    settings = _settings_for_validation()
    strict = _is_strict_environment(settings)
    try:
        _guard_kind(metric, "counter")
        _validate_tags(metric, tags, bucket_registry=_BUCKET_REGISTRY)
    except InstrumentationContractError as err:
        if strict:
            raise
        _record_violation(metric.name, str(err))
        return

    if _should_drop_for_rate_limit(metric):
        _record_violation(metric.name, "rate_limit")
        return

    try:
        sentry_sdk.metrics.count(
            name=metric.name, value=value, unit=metric.unit, attributes=dict(tags or {})
        )
    except Exception:  # noqa: BLE001 — observability never raises
        return


def emit_gauge(
    metric: MetricDef,
    *,
    tags: Mapping[str, str] | None = None,
    value: float,
) -> None:
    """Record a Sentry gauge. Validates against the MetricDef."""

    settings = _settings_for_validation()
    strict = _is_strict_environment(settings)
    try:
        _guard_kind(metric, "gauge")
        _validate_tags(metric, tags, bucket_registry=_BUCKET_REGISTRY)
    except InstrumentationContractError as err:
        if strict:
            raise
        _record_violation(metric.name, str(err))
        return

    try:
        sentry_sdk.metrics.gauge(
            name=metric.name, value=value, unit=metric.unit, attributes=dict(tags or {})
        )
    except Exception:  # noqa: BLE001
        return


def emit_distribution(
    metric: MetricDef,
    *,
    tags: Mapping[str, str] | None = None,
    value: float,
) -> None:
    """Record a Sentry distribution. Validates kind + samples + rate-limits."""

    settings = _settings_for_validation()
    strict = _is_strict_environment(settings)
    try:
        _guard_kind(metric, "distribution")
        _validate_tags(metric, tags, bucket_registry=_BUCKET_REGISTRY)
    except InstrumentationContractError as err:
        if strict:
            raise
        _record_violation(metric.name, str(err))
        return

    if _should_drop_for_sampling(metric, tags):
        return
    if _should_drop_for_rate_limit(metric):
        _record_violation(metric.name, "rate_limit")
        return

    try:
        sentry_sdk.metrics.distribution(
            name=metric.name, value=value, unit=metric.unit, attributes=dict(tags or {})
        )
    except Exception:  # noqa: BLE001
        return


def emit_latency(
    metric: MetricDef,
    *,
    duration_ms: float,
    tags: Mapping[str, str] | None = None,
) -> None:
    """Typed distribution helper — pins unit="ms"."""

    if metric.unit != "ms":
        settings = _settings_for_validation()
        if _is_strict_environment(settings):
            raise InstrumentationContractError(
                f"emit_latency requires unit='ms', got {metric.unit!r} "
                f"for {metric.name!r}"
            )
        _record_violation(metric.name, "latency_non_ms_unit")
        return
    emit_distribution(metric, value=duration_ms, tags=tags)


def emit_failure(
    metric: MetricDef,
    *,
    failure: FailureClass,
    tags: Mapping[str, str] | None = None,
) -> None:
    """Failure counter — injects the `failure_class` tag."""

    if "failure_class" not in metric.allowed_tags:
        settings = _settings_for_validation()
        if _is_strict_environment(settings):
            raise InstrumentationContractError(
                f"emit_failure requires a failure_class-tagged metric; "
                f"got {metric.name!r} with allowed_tags={metric.allowed_tags}"
            )
        _record_violation(metric.name, "failure_without_failure_class_tag")
        return
    full_tags: dict[str, str] = {"failure_class": failure.value}
    if tags:
        full_tags.update(tags)
    emit_counter(metric, tags=full_tags)


@contextlib.contextmanager
def time_latency(
    metric: MetricDef,
    *,
    tags: Mapping[str, str] | None = None,
) -> Iterator[None]:
    """Context manager — record start→stop latency as a one-liner."""

    started = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        emit_latency(metric, duration_ms=elapsed_ms, tags=tags)


# ---- Loop-safe aggregators -------------------------------------------------


class AggregatingCounter:
    """Counter accumulator — emits once on __exit__.

    Only approved way to emit a counter inside a loop when the
    metric's `loop_policy != "allowed"`.
    """

    def __init__(
        self,
        metric: MetricDef,
        *,
        tags: Mapping[str, str] | None = None,
    ) -> None:
        self.metric = metric
        self.tags = dict(tags or {})
        self._total = 0.0

    def add(self, value: float = 1.0) -> None:
        self._total += value

    def __enter__(self) -> AggregatingCounter:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self._total > 0:
            emit_counter(self.metric, tags=self.tags, value=self._total)


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
    ) -> None:
        self.metric = metric
        self.tags = dict(tags or {})
        self._total_ms = 0.0

    def add_ms(self, value: float) -> None:
        self._total_ms += value

    def __enter__(self) -> DurationAccumulator:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self._total_ms > 0:
            emit_latency(self.metric, duration_ms=self._total_ms, tags=self.tags)


__all__ = [
    "AggregatingCounter",
    "DurationAccumulator",
    "InstrumentationContractError",
    "emit_counter",
    "emit_distribution",
    "emit_failure",
    "emit_gauge",
    "emit_latency",
    "init_sentry",
    "register_bucket",
    "time_latency",
]
