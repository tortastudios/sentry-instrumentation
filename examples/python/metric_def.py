"""`MetricDef` schema + five ergonomic classmethods.

Drop-in at `yourapp/shared/metrics.py`. This example reproduces the
shape of a governed metric registry: schema at the top, metric
definitions (or an initially-empty `REGISTRY` list) below.

The constructors fix `kind`/`unit`/`purpose` so call sites only state
the knobs that matter per metric class. Identity is name-based so
registries dedupe as sets, and `Mapping[str, …]` fields for
`tag_constraints` don't need to be hashable.

See also:
  - `metric_tags.py`    — bucket functions referenced by `tag_constraints`
  - `failure_taxonomy.py` — `FailureClass` taxonomy
  - `emission_module.py` — validating emit helpers that consume `MetricDef`
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

MetricKind = Literal["counter", "gauge", "distribution"]
MetricPurpose = Literal["outcome", "latency", "load", "resource", "correctness"]
EmitFrequency = Literal["per_request", "per_step", "per_event", "periodic"]
LoopPolicy = Literal["forbidden", "aggregate_only", "allowed"]
Cardinality = Literal["low", "medium"]
TagConstraint = frozenset[str] | str  # `str` = name of a bucket function


@dataclass(frozen=True, eq=False)
class MetricDef:
    """Governed definition of a single metric.

    Construct via the classmethods (`counter`, `latency`, `gauge`,
    `resource`, `failure_counter`) — they fill in kind/unit/purpose.

    Identity tuple `(name, kind, unit, purpose, allowed_tags,
    tag_constraints)` is immutable once published. Changing any of
    those fields requires a new versioned name.

    Equality + hashing are name-based so two `MetricDef`s with the
    same name dedupe in a set, and `Mapping`-typed fields don't
    break hashability.
    """

    # --- identity (immutable under the same name) ---
    name: str
    kind: MetricKind
    unit: str
    purpose: MetricPurpose

    # --- tagging ---
    allowed_tags: frozenset[str]
    tag_constraints: Mapping[str, TagConstraint]
    cardinality: Cardinality

    # --- cost model ---
    emit_frequency: EmitFrequency
    sampling_rate: float = 1.0
    max_rate_hz: float | None = None
    loop_policy: LoopPolicy = "aggregate_only"

    # --- operational + ownership ---
    operational_meaning: str = ""
    owner: str = ""

    # --- lifecycle ---
    version: int = 1
    deprecated: bool = False
    replaced_by: str | None = None
    retired_at: date | None = None

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MetricDef):
            return NotImplemented
        return self.name == other.name

    # ---- ergonomic constructors ------------------------------------------

    @classmethod
    def counter(
        cls,
        name: str,
        *,
        purpose: MetricPurpose,
        owner: str,
        means: str,
        tags: Mapping[str, TagConstraint] | None = None,
        emit_frequency: EmitFrequency = "per_event",
        sampling_rate: float = 1.0,
        max_rate_hz: float | None = None,
        loop_policy: LoopPolicy = "aggregate_only",
        cardinality: Cardinality = "low",
        version: int = 1,
        deprecated: bool = False,
        replaced_by: str | None = None,
        retired_at: date | None = None,
    ) -> MetricDef:
        """Monotonic counter (`kind="counter"`, `unit="count"`)."""

        tag_constraints = dict(tags or {})
        return cls(
            name=name, kind="counter", unit="count", purpose=purpose,
            allowed_tags=frozenset(tag_constraints),
            tag_constraints=tag_constraints, cardinality=cardinality,
            emit_frequency=emit_frequency, sampling_rate=sampling_rate,
            max_rate_hz=max_rate_hz, loop_policy=loop_policy,
            operational_meaning=means, owner=owner, version=version,
            deprecated=deprecated, replaced_by=replaced_by,
            retired_at=retired_at,
        )

    @classmethod
    def latency(
        cls,
        name: str,
        *,
        owner: str,
        means: str,
        tags: Mapping[str, TagConstraint] | None = None,
        emit_frequency: EmitFrequency = "per_event",
        sampling_rate: float = 1.0,
        max_rate_hz: float | None = None,
        loop_policy: LoopPolicy = "aggregate_only",
        cardinality: Cardinality = "low",
        version: int = 1,
        deprecated: bool = False,
        replaced_by: str | None = None,
        retired_at: date | None = None,
    ) -> MetricDef:
        """Sampled duration (`kind="distribution"`, `unit="ms"`)."""

        tag_constraints = dict(tags or {})
        return cls(
            name=name, kind="distribution", unit="ms", purpose="latency",
            allowed_tags=frozenset(tag_constraints),
            tag_constraints=tag_constraints, cardinality=cardinality,
            emit_frequency=emit_frequency, sampling_rate=sampling_rate,
            max_rate_hz=max_rate_hz, loop_policy=loop_policy,
            operational_meaning=means, owner=owner, version=version,
            deprecated=deprecated, replaced_by=replaced_by,
            retired_at=retired_at,
        )

    @classmethod
    def gauge(
        cls,
        name: str,
        *,
        unit: str,
        owner: str,
        means: str,
        tags: Mapping[str, TagConstraint] | None = None,
        emit_frequency: EmitFrequency = "periodic",
        sampling_rate: float = 1.0,
        max_rate_hz: float | None = None,
        loop_policy: LoopPolicy = "aggregate_only",
        cardinality: Cardinality = "low",
        version: int = 1,
        deprecated: bool = False,
        replaced_by: str | None = None,
        retired_at: date | None = None,
    ) -> MetricDef:
        """Current-state gauge (`kind="gauge"`, `purpose="load"`)."""

        tag_constraints = dict(tags or {})
        return cls(
            name=name, kind="gauge", unit=unit, purpose="load",
            allowed_tags=frozenset(tag_constraints),
            tag_constraints=tag_constraints, cardinality=cardinality,
            emit_frequency=emit_frequency, sampling_rate=sampling_rate,
            max_rate_hz=max_rate_hz, loop_policy=loop_policy,
            operational_meaning=means, owner=owner, version=version,
            deprecated=deprecated, replaced_by=replaced_by,
            retired_at=retired_at,
        )

    @classmethod
    def resource(
        cls,
        name: str,
        *,
        unit: str,
        owner: str,
        means: str,
        tags: Mapping[str, TagConstraint] | None = None,
        emit_frequency: EmitFrequency = "per_event",
        sampling_rate: float = 1.0,
        max_rate_hz: float | None = None,
        loop_policy: LoopPolicy = "aggregate_only",
        cardinality: Cardinality = "low",
        version: int = 1,
        deprecated: bool = False,
        replaced_by: str | None = None,
        retired_at: date | None = None,
    ) -> MetricDef:
        """Resource-consumption counter (`purpose="resource"`).

        For quota units, token counts, bytes — amounts consumed per
        unit work. `unit` is mandatory.
        """

        tag_constraints = dict(tags or {})
        return cls(
            name=name, kind="counter", unit=unit, purpose="resource",
            allowed_tags=frozenset(tag_constraints),
            tag_constraints=tag_constraints, cardinality=cardinality,
            emit_frequency=emit_frequency, sampling_rate=sampling_rate,
            max_rate_hz=max_rate_hz, loop_policy=loop_policy,
            operational_meaning=means, owner=owner, version=version,
            deprecated=deprecated, replaced_by=replaced_by,
            retired_at=retired_at,
        )

    @classmethod
    def failure_counter(
        cls,
        name: str,
        *,
        owner: str,
        means: str,
        tags: Mapping[str, TagConstraint] | None = None,
        emit_frequency: EmitFrequency = "per_event",
        sampling_rate: float = 1.0,
        max_rate_hz: float | None = None,
        loop_policy: LoopPolicy = "aggregate_only",
        cardinality: Cardinality = "low",
        version: int = 1,
        deprecated: bool = False,
        replaced_by: str | None = None,
        retired_at: date | None = None,
    ) -> MetricDef:
        """Failure-outcome counter; always tags with `failure_class`.

        Guarantees `"failure_class"` is in `allowed_tags`, defaulting
        its constraint to the full `FailureClass` taxonomy. Callers
        who pass a tighter `failure_class` constraint win.
        """

        from .failure_taxonomy import FailureClass

        tag_constraints: dict[str, TagConstraint] = dict(tags or {})
        tag_constraints.setdefault(
            "failure_class",
            frozenset(item.value for item in FailureClass),
        )
        return cls(
            name=name, kind="counter", unit="count", purpose="outcome",
            allowed_tags=frozenset(tag_constraints),
            tag_constraints=tag_constraints, cardinality=cardinality,
            emit_frequency=emit_frequency, sampling_rate=sampling_rate,
            max_rate_hz=max_rate_hz, loop_policy=loop_policy,
            operational_meaning=means, owner=owner, version=version,
            deprecated=deprecated, replaced_by=replaced_by,
            retired_at=retired_at,
        )


# Registry used by tests + the CI gate to enforce uniqueness and
# lifecycle rules. Populate with `MetricDef` instances at module
# scope below, then reference the symbol from call sites.
REGISTRY: list[MetricDef] = []


__all__ = [
    "Cardinality",
    "EmitFrequency",
    "LoopPolicy",
    "MetricDef",
    "MetricKind",
    "MetricPurpose",
    "REGISTRY",
    "TagConstraint",
]
