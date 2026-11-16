"""Pytest gates for the governed-instrumentation layer — reference cases.

Drop-in at `tests/test_observability_gates.py`. These tests
pin the contracts that the helper API and registry must uphold.

The layout mirrors the concern areas:

  - Emission-helper validation (reject unknown tags, wrong kinds, etc.)
  - Registry integrity (every MetricDef has required fields, no
    duplicates, naming regex)
  - Failure taxonomy (classifier maps known exceptions, UNKNOWN for
    unmapped)
  - Loop-safety helpers (AggregatingCounter, DurationAccumulator)
  - Rate limiter + sampling determinism

Tests replace the emission module's `_sink` — the one function that
calls `sentry_sdk.metrics.*` — with a recorder, so they assert on what
would be sent without a DSN.

Runnable in this repo: `conftest.py` maps the example files onto the
`yourapp.*` import paths. Under pytest the helpers are always in strict
mode, so validation raises rather than drops.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest

import yourapp.observability as observability
from yourapp.observability import (
    AggregatingCounter,
    DurationAccumulator,
    InstrumentationContractError,
    emit_counter,
    emit_distribution,
    emit_failure,
    emit_gauge,
    emit_latency,
)
from yourapp.shared.failure_taxonomy import FailureClass, classify, register
from yourapp.shared.metrics import REGISTRY, MetricDef

# ---- Helpers --------------------------------------------------------------


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Capture what the helpers would hand to `sentry_sdk.metrics.*`."""

    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_emit(kind: str, **payload: Any) -> None:
        captured.append((kind, payload))

    monkeypatch.setattr(observability, "_sink", fake_emit)
    monkeypatch.setattr(observability, "_rate_buckets", {})
    return captured


def _counter(**overrides: Any) -> MetricDef:
    defaults: dict[str, Any] = {
        "name": "test.event.count",
        "purpose": "outcome",
        "owner": "platform",
        "tags": {"status": frozenset({"ok", "fail"})},
        "means": "Test counter.",
        "emit_frequency": "per_event",
    }
    defaults.update(overrides)
    name = defaults.pop("name")
    return MetricDef.counter(name, **defaults)


# ---- Emission-helper validation -------------------------------------------


def test_emit_rejects_unknown_tag_key(sink: list[Any]) -> None:
    m = _counter()
    with pytest.raises(InstrumentationContractError, match="unknown tag"):
        emit_counter(m, tags={"status": "ok", "nonsense": "x"})
    assert sink == []


def test_emit_rejects_tag_value_outside_constraints(sink: list[Any]) -> None:
    m = _counter()
    with pytest.raises(InstrumentationContractError, match="tag value"):
        emit_counter(m, tags={"status": "weird"})
    assert sink == []


def test_emit_rejects_wrong_kind(sink: list[Any]) -> None:
    latency = MetricDef.latency(
        "test.op.duration",
        owner="platform",
        tags={},
        means="Test latency.",
        emit_frequency="per_event",
    )
    with pytest.raises(InstrumentationContractError, match="kind"):
        emit_counter(latency, tags={})


def test_emit_failure_requires_failure_class_tag(sink: list[Any]) -> None:
    f = MetricDef.failure_counter(
        "test.op.failure.count",
        owner="platform",
        tags={},
        means="Test failure counter.",
        emit_frequency="per_event",
    )
    # emit_failure injects failure_class from the FailureClass arg.
    emit_failure(f, failure=FailureClass.TIMEOUT, tags={})
    assert sink and sink[0][1]["attributes"]["failure_class"] == "timeout"

    # emit_counter on a failure_counter without the tag must raise.
    with pytest.raises(InstrumentationContractError, match="failure_class"):
        emit_counter(f, tags={})


def test_emit_latency_rejects_non_ms_unit(sink: list[Any]) -> None:
    # Construct a distribution with a non-ms unit and ensure emit_latency
    # refuses it. (emit_distribution with a seconds metric still works
    # — latency is the typed lane.)
    secs = MetricDef(
        name="test.op.seconds",
        kind="distribution",
        unit="second",
        purpose="latency",
        allowed_tags=frozenset(),
        tag_constraints={},
        cardinality="low",
        emit_frequency="per_event",
        operational_meaning="Test.",
        owner="platform",
    )
    with pytest.raises(InstrumentationContractError, match="unit"):
        emit_latency(secs, duration_ms=1.0, tags={})


def test_emit_latency_accepts_both_millisecond_spellings(sink: list[Any]) -> None:
    current = MetricDef.latency(
        "test.op.duration", owner="platform", tags={}, means="Test.",
        emit_frequency="per_event",
    )
    legacy = MetricDef.latency(
        "test.legacy.duration", owner="platform", tags={}, means="Test.",
        emit_frequency="per_event", unit="ms",
    )
    emit_latency(current, duration_ms=1.0)
    emit_latency(legacy, duration_ms=1.0)
    assert [e[1]["unit"] for e in sink] == ["millisecond", "ms"]


# ---- Debug-context attributes ----------------------------------------------


def test_context_is_sent_alongside_tags(sink: list[Any]) -> None:
    m = _counter(context={"account_id", "project_id"})
    emit_counter(
        m, tags={"status": "ok"}, context={"account_id": "acct_42", "project_id": 7}
    )
    assert sink[0][1]["attributes"] == {
        "status": "ok", "account_id": "acct_42", "project_id": 7,
    }


def test_emit_rejects_undeclared_context_key(sink: list[Any]) -> None:
    m = _counter(context={"account_id"})
    with pytest.raises(InstrumentationContractError, match="context key"):
        emit_counter(m, tags={"status": "ok"}, context={"request_id": "r1"})
    assert sink == []


def test_emit_rejects_free_text_context_value(sink: list[Any]) -> None:
    m = _counter(context={"account_id"})
    with pytest.raises(InstrumentationContractError, match="longer than"):
        emit_counter(m, tags={"status": "ok"}, context={"account_id": "x" * 500})
    with pytest.raises(InstrumentationContractError, match="str/int/float/bool"):
        emit_counter(m, tags={"status": "ok"}, context={"account_id": ["a"]})
    assert sink == []


def test_context_key_cannot_shadow_a_tag() -> None:
    with pytest.raises(ValueError, match="both a tag and a context"):
        _counter(context={"status"})


@pytest.mark.parametrize("key", ["email", "prompt", "error_message", "sentry.release", "user.id"])
def test_forbidden_or_reserved_context_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        _counter(context={key})


# ---- Registry integrity ---------------------------------------------------


def test_registry_has_no_duplicate_names() -> None:
    names = [m.name for m in REGISTRY]
    assert len(names) == len(set(names)), (
        f"Duplicate metric names: "
        f"{sorted({n for n in names if names.count(n) > 1})}"
    )


def test_every_metric_def_has_required_fields() -> None:
    for m in REGISTRY:
        assert m.name
        assert m.kind in {"counter", "gauge", "distribution"}
        assert m.unit
        assert m.purpose in {
            "outcome", "latency", "load", "resource", "correctness",
        }
        assert m.owner, f"{m.name!r} missing owner"
        assert m.operational_meaning, f"{m.name!r} missing operational_meaning"
        assert m.emit_frequency in {
            "per_request", "per_step", "per_event", "periodic",
        }


def test_registry_names_match_regex() -> None:
    import re
    pattern = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+(\.v\d+)?$")
    for m in REGISTRY:
        assert pattern.match(m.name), f"{m.name!r} fails naming regex"


def test_no_metric_retired_in_past() -> None:
    today = date.today()
    past = [
        m for m in REGISTRY
        if m.retired_at is not None and m.retired_at < today
    ]
    assert not past, (
        f"Metrics past their retired_at are still in the registry — "
        f"remove them: {[m.name for m in past]}"
    )


def test_deprecated_metrics_have_replacement() -> None:
    for m in REGISTRY:
        if m.deprecated:
            assert m.replaced_by, f"{m.name!r} is deprecated but has no replaced_by"
            assert m.retired_at, f"{m.name!r} is deprecated but has no retired_at"


# ---- Failure taxonomy -----------------------------------------------------


def test_classify_maps_stdlib_exceptions() -> None:
    assert classify(asyncio.TimeoutError()) is FailureClass.TIMEOUT
    assert classify(asyncio.CancelledError()) is FailureClass.CANCELLED
    assert classify(ValueError("bad")) is FailureClass.VALIDATION_FAILURE


def test_classify_unknown_returns_unknown() -> None:
    class _Novel(Exception):
        pass

    assert classify(_Novel()) is FailureClass.UNKNOWN


def test_classify_walks_mro() -> None:
    class _ParentError(Exception):
        pass

    class _ChildError(_ParentError):
        pass

    register(_ParentError, FailureClass.DEPENDENCY_FAILURE)
    try:
        assert classify(_ChildError()) is FailureClass.DEPENDENCY_FAILURE
    finally:
        register(_ParentError, None)  # teardown — implementations expose this.


# ---- Loop-safety helpers --------------------------------------------------


def test_aggregating_counter_emits_once_at_exit(sink: list[Any]) -> None:
    m = _counter()
    with AggregatingCounter(m, tags={"status": "ok"}) as c:
        for _ in range(1000):
            c.add()
    counter_emissions = [e for e in sink if e[0] == "counter"]
    assert len(counter_emissions) == 1
    assert counter_emissions[0][1]["value"] == 1000


def test_duration_accumulator_emits_single_sample(sink: list[Any]) -> None:
    m = MetricDef.latency(
        "test.batch.duration",
        owner="platform",
        tags={},
        means="Sum of per-item durations in a batch.",
        emit_frequency="per_event",
    )
    with DurationAccumulator(m, tags={}) as d:
        for value in (1.0, 2.0, 3.0):
            d.add_ms(value)
    dist_emissions = [e for e in sink if e[0] == "distribution"]
    assert len(dist_emissions) == 1
    assert dist_emissions[0][1]["value"] == pytest.approx(6.0)


def test_aggregating_counter_does_not_emit_if_never_incremented(sink: list[Any]) -> None:
    m = _counter()
    with AggregatingCounter(m, tags={"status": "ok"}):
        pass
    # Zero increments → no emission (don't pollute aggregations with
    # empty samples).
    assert [e for e in sink if e[0] == "counter"] == []


# ---- Rate limiter + sampling ----------------------------------------------


def test_rate_limiter_drops_beyond_max_rate_hz(sink: list[Any]) -> None:
    m = _counter(max_rate_hz=5.0)
    for _ in range(100):
        emit_counter(m, tags={"status": "ok"})
    sent = [e for e in sink if e[1]["name"] == "test.event.count"]
    assert len(sent) == 5

    # Drops are reported as ONE event carrying the total, not one per drop.
    observability.flush_rate_limit_drops()
    drops = [
        e for e in sink
        if e[1]["name"] == "instrumentation.rate_limit.drop_count"
    ]
    assert len(drops) == 1
    assert drops[0][1]["value"] == 95
    assert drops[0][1]["attributes"] == {"metric": "test.event.count"}


def test_sampling_keeps_a_fraction_of_every_tag_group(
    monkeypatch: pytest.MonkeyPatch, sink: list[Any]
) -> None:
    import random

    monkeypatch.setattr(observability, "_rng", random.Random(1234))
    m = MetricDef.latency(
        "test.sampled.duration",
        owner="platform",
        tags={"bucket": frozenset({"a", "b", "c", "d", "e"})},
        means="Test sampling.",
        emit_frequency="per_event",
        sampling_rate=0.5,
    )
    for bucket in "abcde":
        for _ in range(400):
            emit_distribution(m, tags={"bucket": bucket}, value=1.0)
    kept = {b: 0 for b in "abcde"}
    for _, payload in sink:
        kept[payload["attributes"]["bucket"]] += 1
    # No tag group is dropped wholesale; each keeps roughly half.
    for bucket, n in kept.items():
        assert 150 < n < 250, f"bucket={bucket} kept {n}/400"


def test_counters_are_never_sampled(sink: list[Any]) -> None:
    m = _counter(sampling_rate=0.01)
    for _ in range(50):
        emit_counter(m, tags={"status": "ok"})
    assert len(sink) == 50


# ---- Production fail-safety ----------------------------------------------


def test_violation_drops_silently_in_production(
    monkeypatch: pytest.MonkeyPatch, sink: list[Any]
) -> None:
    monkeypatch.setattr(observability, "_is_strict_environment", lambda: False)
    m = _counter()
    # Bad tag value — in production this drops + emits a violation
    # counter, never raises.
    emit_counter(m, tags={"status": "nope"})
    assert [e[1]["name"] for e in sink] == ["instrumentation.violation.count"]
    # The rule attribute is a fixed code, not the error message text.
    assert sink[0][1]["attributes"] == {
        "metric": "test.event.count",
        "rule": "tag_value_outside_constraints",
    }


def test_emit_swallows_sdk_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(kind: str, **payload: Any) -> None:
        raise RuntimeError("sdk exploded")

    monkeypatch.setattr(observability, "_sink", boom)
    emit_counter(_counter(), tags={"status": "ok"})  # must not raise
    emit_gauge(
        MetricDef.gauge(
            "test.queue.depth", unit="items", owner="platform", tags={},
            means="Test gauge.", emit_frequency="periodic",
        ),
        value=3.0,
    )


def test_noops_when_unconfigured() -> None:
    # No DSN, SDK never initialized: the real sink must be a silent no-op.
    emit_counter(_counter(), tags={"status": "ok"})


def test_real_sdk_receives_attributes_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the call shape against the installed sentry-sdk."""

    import inspect

    import sentry_sdk

    for fn in (
        sentry_sdk.metrics.count,
        sentry_sdk.metrics.gauge,
        sentry_sdk.metrics.distribution,
    ):
        params = inspect.signature(fn).parameters
        assert list(params)[:2] == ["name", "value"]
        assert "attributes" in params and "unit" in params
        assert "tags" not in params
