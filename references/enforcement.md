# Enforcement — CI + tests

Rules on paper decay. This skill expects the project to carry a CI
gate and a set of pytest gates that turn each rule into an automated
check.

## CI gate — `check_metrics` script

AST-based (use your language's AST tooling: Python `ast`, TypeScript
`ts-morph` or `ast-grep`, Go `go/ast`, Ruby `parser`). Wired into the
project's check loop — `make check`, `npm run lint`, `pre-commit`,
`just check`, `bundle exec rake check`, or a required GitHub Actions
/ GitLab CI job — so PRs can't merge when it fails. See
`examples/python/ci_gate.py` for the Python reference implementation
that covers all 13 checks; port the same rules to your language using
its AST library.

### The 13 checks

1. **SDK-only emission isolation.** `sentry_sdk.metrics.*` is called
   only from the emission module (e.g., `yourapp/observability.py`).
   Every other module must go through the validating helpers.
2. **`emit_*` first arg is a `MetricDef` symbol.** Rejects raw
   strings, f-strings, `.format()`, and variables. Calls like
   `emit_counter("cache.hit", ...)` fail the gate.
3. **Required `MetricDef` fields.** Every entry has `name`, `kind`,
   `unit`, `purpose`, `allowed_tags`, `tag_constraints`, `cardinality`,
   `emit_frequency`, `operational_meaning`, `owner`.
4. **No duplicate metric names.** Registry is a set by name; two
   entries with the same name fail.
5. **Name regex.** Matches `<domain>.<object>.<action>[.<type-suffix>]`.
6. **Medium cardinality justified.** `cardinality="medium"` requires
   a justification paragraph in `means=`.
7. **Tag keys are in `allowed_tags` at call sites.** AST-walk every
   `emit_*` call's `tags={}` literal against the target metric's
   allowed tag set.
8. **Deprecated entry has `replaced_by` and `retired_at`.** Under-
   specified deprecation fails.
9. **`retired_at` not in the past.** Past-dated entries must be
   removed.
10. **Identity tuple immutable.** Diff the PR against `main`; if
    `(name, kind, unit, purpose, allowed_tags, tag_constraints)`
    changed for an existing entry, fail — must be a new versioned
    name.
11. **No silent removal.** A non-deprecated entry removed from the
    registry fails. Removal requires a prior PR that sets
    `deprecated=True` with `retired_at`.
12. **Loop-policy enforcement.** `emit_counter` /
    `emit_distribution` inside a `for`/`while` body for a metric with
    `loop_policy != "allowed"` fails unless wrapped in
    `AggregatingCounter` / `DurationAccumulator`, or marked with the
    escape comment `# instrumentation: loop-aggregate` and a
    rationale.
13. **No dynamic metric names.** Any `MetricDef(name=f"..." / <expr>)`
    fails — names must be literal strings.

### Running locally

```shell
# Python reference:
python scripts/check_metrics.py \
    --registry yourapp/shared/metrics.py \
    --emission-module yourapp/observability.py \
    --project-root yourapp

# Or integrate into your project's check loop:
make check            # GNU make
npm run lint          # Node/TS
pre-commit run --all  # pre-commit framework
just check            # just runner
bundle exec rake check  # Ruby
```

A fail prints the offending file:line + the rule it broke. No fix-it
mode — the gate is purely diagnostic so reviewers can't bypass it
with auto-fix.

## Pytest gates

Live in the project's test suite (e.g., `yourapp/tests/`). See
`examples/python/test_gates.py` for the reference cases — ports to
other languages should translate the same cases to the language's
idiomatic test framework (Jest/Vitest for TS, `go test` for Go, RSpec
for Ruby).

Keep these three from the original observability tests (they protect
the fail-safe contract that lets the helpers run in production):

- `test_init_sentry_noops_when_unconfigured`
- `test_emit_*_swallows_sdk_exceptions`
- `test_init_sentry_is_noop_under_pytest`

### New gates for the governed layer

Contract-level:

- `test_emit_rejects_unknown_tag_key`
- `test_emit_rejects_tag_value_outside_constraints`
- `test_emit_rejects_wrong_kind`
- `test_emit_failure_requires_failure_class_tag`
- `test_emit_latency_rejects_non_ms_unit`

Registry-level:

- `test_registry_has_no_duplicate_names`
- `test_every_metric_def_has_required_fields`
- `test_classify_maps_known_exceptions_to_taxonomy`
- `test_classify_returns_unknown_for_unmapped_exception`

Production-fallback-level:

- `test_violation_counter_emits_in_production_path` — validator
  failures in production drop the emission + emit
  `instrumentation.violation.count`, never raise.

Cost-model-level:

- `test_aggregating_counter_emits_once_at_exit`
- `test_duration_accumulator_emits_single_sample`
- `test_rate_limiter_drops_beyond_max_rate_hz`
- `test_sampling_rate_determinism_by_tag_hash`

## Where to put the escape hatch

The loop-policy escape comment exists because AST enforcement has
edge cases:

```python
for batch in batches:
    emit_counter(BATCH_PROCESSED, tags={...})  # instrumentation: loop-aggregate
```

Use sparingly. Every occurrence in the codebase is a signal that
either the metric's `loop_policy` should be widened (maybe
`"allowed"` is correct for this metric) or the loop should be
refactored to use `AggregatingCounter`. Reviewers should push back on
any PR that adds more than one new escape hatch.

## Interaction with production behavior

CI enforces the static rules; the helper API enforces the dynamic
ones (tag values, wrong kind, failure-class requirement). In
production, the helper API *never raises* — it drops the emission and
bumps `instrumentation.violation.count`. That counter is itself a
`correctness` metric the project alerts on: a sustained non-zero rate
means the CI gate has a blind spot the helpers are catching at
runtime.
