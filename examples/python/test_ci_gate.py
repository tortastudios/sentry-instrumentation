"""Tests for the CI gate itself — each case is a tiny project on disk.

Loads `ci_gate.py` by path, writes a registry + one call-site module
into `tmp_path`, runs the gate, and asserts on the check IDs reported.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "ci_gate", Path(__file__).parent / "ci_gate.py"
)
assert _spec is not None and _spec.loader is not None
ci_gate = importlib.util.module_from_spec(_spec)
sys.modules["ci_gate"] = ci_gate
_spec.loader.exec_module(ci_gate)

REGISTRY = """
    from yourapp.shared.metrics import MetricDef

    CHECKOUT_FAILED = MetricDef.failure_counter(
        "checkout.payment.failure.count",
        owner="payments",
        means="A payment attempt failed.",
        tags={"provider": frozenset({"stripe", "adyen"})},
        context={"account_id", "order_id"},
        emit_frequency="per_event",
    )
    ROW_DURATION = MetricDef.latency(
        "ingest.row.duration",
        owner="platform",
        means="Per-row processing time.",
        tags={},
        emit_frequency="per_event",
        loop_policy="allowed",
    )
    REQUEST_COUNT = MetricDef.counter(
        "api.request.count",
        purpose="outcome",
        owner="platform",
        means="One per request.",
        tags={},
        emit_frequency="per_request",
        loop_policy="forbidden",
    )
"""


def run_gate(
    tmp_path: Path, call_site: str, *, registry: str = REGISTRY,
    baseline: str | None = None,
) -> list[str]:
    root = tmp_path / "yourapp"
    root.mkdir()
    registry_path = root / "metrics.py"
    registry_path.write_text(textwrap.dedent(registry))
    emission = root / "observability.py"
    emission.write_text("")
    (root / "site.py").write_text(textwrap.dedent(call_site))

    entries, violations = ci_gate.collect_registry(registry_path)
    violations += ci_gate.check_registry(registry_path, entries)
    violations += ci_gate.check_call_sites(root, emission, entries)
    if baseline is not None:
        baseline_path = tmp_path / "baseline.py"
        baseline_path.write_text(textwrap.dedent(baseline))
        old, _ = ci_gate.collect_registry(baseline_path)
        violations += ci_gate.check_baseline(registry_path, entries, old)
    return [v.code for v in violations]


def test_clean_project_passes(tmp_path: Path) -> None:
    codes = run_gate(tmp_path, """
        emit_failure(
            CHECKOUT_FAILED,
            failure=classify(exc),
            tags={"provider": "stripe"},
            context={"account_id": account.id, "order_id": order.id},
        )
    """)
    assert codes == []


def test_m001_direct_sdk_call(tmp_path: Path) -> None:
    codes = run_gate(tmp_path, 'sentry_sdk.metrics.count("x.y.z", 1)\n')
    assert codes == ["M001"]


def test_m002_raw_string_metric(tmp_path: Path) -> None:
    assert run_gate(tmp_path, 'emit_counter("cache.hit", tags={})\n') == ["M002"]


def test_m007_undeclared_tag_key(tmp_path: Path) -> None:
    codes = run_gate(tmp_path, """
        emit_failure(CHECKOUT_FAILED, failure=f, tags={"region": "eu"})
    """)
    assert codes == ["M007"]


def test_m007_high_cardinality_id_as_tag_is_caught(tmp_path: Path) -> None:
    # An id belongs in context=, not in the group-by tags.
    codes = run_gate(tmp_path, """
        emit_failure(CHECKOUT_FAILED, failure=f, tags={"account_id": account.id})
    """)
    assert codes == ["M007"]


def test_m014_undeclared_context_key(tmp_path: Path) -> None:
    codes = run_gate(tmp_path, """
        emit_failure(CHECKOUT_FAILED, failure=f, tags={"provider": "stripe"},
                     context={"session_id": s.id})
    """)
    assert codes == ["M014"]


@pytest.mark.parametrize(
    "context",
    ['{"email"}', '{"sentry.release"}', '{"user.id"}', '{"provider"}', "KEYS"],
)
def test_m014_bad_context_declaration(tmp_path: Path, context: str) -> None:
    registry = f"""
        M = MetricDef.counter(
            "checkout.payment.count",
            purpose="outcome",
            owner="payments",
            means="One per payment attempt.",
            tags={{"provider": frozenset({{"stripe"}})}},
            context={context},
            emit_frequency="per_event",
        )
    """
    assert run_gate(tmp_path, "", registry=registry) == ["M014"]


def test_m012_respects_loop_policy(tmp_path: Path) -> None:
    codes = run_gate(tmp_path, """
        for row in rows:
            emit_latency(ROW_DURATION, duration_ms=1.0)       # allowed
            emit_counter(REQUEST_COUNT)  # instrumentation: loop-aggregate: nope
            emit_failure(CHECKOUT_FAILED, failure=f, tags={"provider": "stripe"})
    """)
    # ROW_DURATION is allowed; REQUEST_COUNT is forbidden even with the
    # escape comment; CHECKOUT_FAILED has the default policy.
    assert codes == ["M012", "M012"]


def test_m012_aggregator_and_escape_comment(tmp_path: Path) -> None:
    codes = run_gate(tmp_path, """
        with AggregatingCounter(CHECKOUT_FAILED, tags={"provider": "stripe"}) as c:
            for row in rows:
                c.add()
        for row in rows:
            # instrumentation: loop-aggregate: one event per provider call
            emit_failure(CHECKOUT_FAILED, failure=f, tags={"provider": "stripe"})
    """)
    assert codes == []


def test_m010_identity_change_and_m011_silent_removal(tmp_path: Path) -> None:
    baseline = REGISTRY.replace('{"stripe", "adyen"}', '{"stripe"}') + """
    GONE = MetricDef.counter(
        "cache.lookup.count", purpose="outcome", owner="platform",
        means="One per lookup.", tags={}, emit_frequency="per_event",
    )
    """
    codes = run_gate(tmp_path, "", baseline=baseline)
    assert sorted(codes) == ["M010", "M011"]


def test_adding_context_is_not_an_identity_change(tmp_path: Path) -> None:
    baseline = REGISTRY.replace('context={"account_id", "order_id"},', "")
    assert run_gate(tmp_path, "", baseline=baseline) == []
