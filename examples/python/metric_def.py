"""`MetricDef` schema + five ergonomic classmethods.

Drop-in at `yourapp/shared/metrics.py`. This example reproduces the
shape of a governed metric registry: schema at the top, metric
definitions (or an initially-empty `REGISTRY` list) below.

The constructors fix `kind`/`unit`/`purpose` so call sites only state
the knobs that matter per metric class. Identity is name-based so
registries dedupe as sets, and `Mapping[str, …]` fields for
`tag_constraints` don't need to be hashable.

Two kinds of attribute, both sent to Sentry as metric `attributes`:

  - `tags=`     group-by dimensions. Closed sets (enumerated values or a
                bucket function). These are what dashboards and alert
                rules group and filter on, so they must stay stable.
  - `context=`  debug-context attributes. Declared key names whose values
                are free (ids such as `account_id`, `project_id`,
                `replay_id`). Sentry stores each metric as a full event,
                so these are queryable; they are there to find the
                affected customer or request, not to drive alerts.

See `references/tagging-and-cardinality.md` for the reasoning and the
Sentry sources.

See also:
  - `metric_tags.py`    — bucket functions referenced by `tag_constraints`
  - `failure_taxonomy.py` — `FailureClass` taxonomy
  - `emission_module.py` — validating emit helpers that consume `MetricDef`
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

MetricKind = Literal["counter", "gauge", "distribution"]
MetricPurpose = Literal["outcome", "latency", "load", "resource", "correctness"]
EmitFrequency = Literal["per_request", "per_step", "per_event", "periodic"]
LoopPolicy = Literal["forbidden", "aggregate_only", "allowed"]
Cardinality = Literal["low", "medium"]
TagConstraint = frozenset[str] | str  # `str` = name of a bucket function

# Units. Sentry's Python docs and the SDK's typed unit literals spell
# durations and sizes out ("millisecond", "byte"). "ms" is accepted for
# metrics that were registered before this skill adopted that spelling:
# the unit is part of a metric's identity, so don't rewrite it in place.
LATENCY_UNITS: frozenset[str] = frozenset({"millisecond", "ms"})

# Keys that may never be declared as context. This is this skill's own
# policy (privacy + payload size), not a Sentry limit: free-form text and
# direct personal data don't belong on a metric event at all.
FORBIDDEN_CONTEXT_KEYS: frozenset[str] = frozenset({
    "email", "user_email", "ip", "ip_address", "user_agent",
    "prompt", "completion", "message", "body", "text",
    "error", "error_message", "exception", "stack", "stacktrace",
    "url", "raw_url", "query", "query_string", "path",
})

# `sentry.*` is the SDK's own attribute namespace (sentry.environment,
# sentry.release, sentry.sdk.*). `user.*` is filled in by the SDK from
# `sentry_sdk.set_user(...)` when user-info collection is on; set the
# user on the scope instead of redeclaring it here.
RESERVED_CONTEXT_PREFIXES: tuple[str, ...] = ("sentry.", "user.")


@dataclass(frozen=True, eq=False)
class MetricDef:
    """Governed definition of a single metric.

    Construct via the classmethods (`counter`, `latency`, `gauge`,
    `resource`, `failure_counter`) — they fill in kind/unit/purpose.

    Identity tuple `(name, kind, unit, purpose, allowed_tags,
    tag_constraints)` is immutable once published. Changing any of
    those fields requires a new versioned name. `context_attributes`
    is not part of the identity: adding a debug-context key doesn't
    change what the metric measures or how it groups.

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

    # --- debug context (free-valued attributes, never grouped/alerted on) ---
    context_attributes: frozenset[str] = frozenset()

    # --- operational + ownership ---
    operational_meaning: str = ""
    owner: str = ""

    # --- lifecycle ---
    version: int = 1
    deprecated: bool = False
    replaced_by: str | None = None
    retired_at: date | None = None

    def __post_init__(self) -> None:
        overlap = self.context_attributes & self.allowed_tags
        if overlap:
            raise ValueError(
                f"metric {self.name!r}: {sorted(overlap)} declared as both a "
                f"tag and a context attribute"
            )
        for key in self.context_attributes:
            if key in FORBIDDEN_CONTEXT_KEYS or key.startswith(
                RESERVED_CONTEXT_PREFIXES
            ):
                raise ValueError(
                    f"metric {self.name!r}: context key {key!r} is not allowed"
                )

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
        context: Iterable[str] | None = None,
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
            context_attributes=frozenset(context or ()),
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
        context: Iterable[str] | None = None,
        unit: str = "millisecond",
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
        """Duration distribution, always measured in milliseconds.

        `unit` is the string sent to Sentry: `"millisecond"` (default)
        or `"ms"` for metrics registered before the default changed.
        """

        if unit not in LATENCY_UNITS:
            raise ValueError(
                f"metric {name!r}: latency unit must be one of "
                f"{sorted(LATENCY_UNITS)}, got {unit!r}"
            )
        tag_constraints = dict(tags or {})
        return cls(
            name=name, kind="distribution", unit=unit, purpose="latency",
            allowed_tags=frozenset(tag_constraints),
            tag_constraints=tag_constraints, cardinality=cardinality,
            context_attributes=frozenset(context or ()),
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
        context: Iterable[str] | None = None,
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
            context_attributes=frozenset(context or ()),
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
        context: Iterable[str] | None = None,
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
            context_attributes=frozenset(context or ()),
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
        context: Iterable[str] | None = None,
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
            context_attributes=frozenset(context or ()),
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
    "FORBIDDEN_CONTEXT_KEYS",
    "LATENCY_UNITS",
    "EmitFrequency",
    "LoopPolicy",
    "MetricDef",
    "MetricKind",
    "MetricPurpose",
    "REGISTRY",
    "TagConstraint",
]
