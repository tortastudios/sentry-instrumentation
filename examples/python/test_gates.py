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

Tests use a fake Sentry sink captured via an env-var toggle on the
emission module — real implementations either monkey-patch
`sentry_sdk.metrics` or expose a pluggable sink. The important
contract is what gets emitted (or not) and whether the helper raises,
not the specific sink.

These tests should run in strict mode (`settings.environment !=
"production"`) so validation raises rather than drops.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest

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
    """Capture emissions. Replace with your project's fake-sink hook."""

    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_emit(kind: str, **payload: Any) -> None:
        captured.append((kind, payload))

    monkeypatch.setattr("yourapp.observability._sink", fake_emit)
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
    assert sink and sink[0][1]["tags"]["failure_class"] == "timeout"

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
        unit="s",
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
            c.inc()
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
    counter_emissions = [e for e in sink if e[0] == "counter"]
    # Strictly fewer than 100 — the exact cap depends on token-bucket
    # implementation, but the contract is that the ceiling is honored.
    assert len(counter_emissions) < 100
    # A violation counter must have fired for the drops.
    violations = [
        e for e in sink
        if e[0] == "counter"
        and e[1].get("name", "").startswith("instrumentation.rate_limit")
    ]
    assert violations


def test_sampling_rate_is_deterministic_by_tag_hash(sink: list[Any]) -> None:
    m = MetricDef.latency(
        "test.sampled.duration",
        owner="platform",
        tags={"bucket": frozenset({"a", "b", "c", "d", "e"})},
        means="Test deterministic sampling.",
        emit_frequency="per_event",
        sampling_rate=0.5,
    )
    # Emit 100 times per tag; the decision must be the same for every
    # emission with the same tag set.
    results: dict[str, set[bool]] = {}
    for bucket in "abcde":
        results[bucket] = set()
        for _ in range(100):
            before = len([e for e in sink if e[0] == "distribution"])
            emit_distribution(m, tags={"bucket": bucket}, value=1.0)
            after = len([e for e in sink if e[0] == "distribution"])
            results[bucket].add(after > before)
    # Each tag set is either always sampled or always dropped — never
    # both.
    for bucket, decisions in results.items():
        assert len(decisions) == 1, (
            f"Sampling non-deterministic for bucket={bucket}: {decisions}"
        )


# ---- Production fail-safety ----------------------------------------------


def test_violation_drops_silently_in_production(
    monkeypatch: pytest.MonkeyPatch, sink: list[Any]
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    # Reimport or re-instantiate so the helper reads the env.
    # (Implementation-specific.)
    from yourapp.observability import emit_counter as prod_emit
    m = _counter()
    # Bad tag — in production this drops + emits a violation counter,
    # never raises.
    prod_emit(m, tags={"status": "nope"})
    # No exception raised. Violation counter should be recorded.
    violations = [
        e for e in sink
        if e[0] == "counter"
        and e[1].get("name", "").startswith("instrumentation.violation")
    ]
    assert violations


def test_noops_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRY_DSN", "")
    # Re-init the module (project-specific) and verify emit_* is a no-op
    # when the SDK isn't configured. The contract: no exception, no I/O.
    from yourapp.observability import emit_counter as bare_emit
    bare_emit(_counter(), tags={"status": "ok"})  # must not raise
