# Naming and lifecycle

The names of the metrics and their meanings are **contracts** with every
downstream consumer — dashboards, alert rules, post-incident queries,
runbooks. A silent rename breaks all of them at once.

## Naming

- Format: `<domain>.<object>.<action>[.<type-suffix>]`.
  - `<domain>`: `api`, `worker`, `external_api`, `cache`, `llm`, `db`,
    etc. (stay language-neutral — these are logical domains, not
    framework names).
  - `<object>`: the entity — `request`, `job`, `query`, `quota`,
    `token`, `connection`.
  - `<action>`: the verb — `count`, `duration`, `depth`, `units`,
    `hit`, `miss`.
  - `<type-suffix>` (optional): disambiguates when the same action word
    is used for multiple kinds — `.count`, `.duration_ms`, `.value`.
- Lowercase, dot-separated, snake_case within a segment.
- No abbreviations outside the domain vocabulary (`http`, `db`, `id`
  OK; `pipe` for `pipeline` not OK).
- Every metric name resolves to exactly one `MetricDef` at import
  time. Enforced by `test_registry_has_no_duplicate_names`.
- Dynamic metric names (f-strings, `.format`, runtime concatenation)
  are forbidden. The helper API refuses non-`MetricDef` first arguments;
  the CI gate refuses `emit_*(f"...", ...)` at the AST level.

## Lifecycle

### Identity is immutable under the same name

The tuple `(name, kind, unit, purpose, allowed_tags, tag_constraints)`
is the metric's identity. Once published (merged to `main`), these
fields **cannot change** for that name. If the meaning must change
(even slightly — e.g., "now we also include the cache-hit path"), the
result is a new metric with a new name.

**Why:** dashboards, alert rules, and post-mortem queries reference
metrics by name. Changing what a name means silently invalidates
every consumer, with no audit trail. A rename forces the consumers to
migrate explicitly.

### Version suffix rule

When a metric's semantics must change:

1. Add a *new* `MetricDef` entry with the new semantics, named
   `<original>.v2` (or `.v3`, etc.). Its `version` field starts at 2.
2. Mark the original `MetricDef` as `deprecated=True` and set:
   - `replaced_by="<new-name>"`
   - `retired_at=<today + 14 days>`
3. Both metrics emit for the overlap window. Consumers migrate
   dashboards/alerts to the new name during the window.
4. On or after `retired_at`, the old entry is removed in a PR that
   also strips the emission sites.

No silent renames. No in-place identity changes.

### CI lifecycle enforcement

The CI gate fails on:

- `retired_at` in the past on a still-present entry → forces removal
  on schedule.
- A non-deprecated entry removed from the registry → silent deletion
  is worse than leftover; the deprecation flow exists for a reason.
- A change to any field of the identity tuple on an existing entry
  (diff vs. `main`) → must be a new versioned name instead.
- A deprecated entry with no `replaced_by` or no `retired_at` →
  under-specified deprecation.

### Tag keys are never repurposed

A new meaning for an existing tag key requires a new tag key.
Example: if `status` used to mean HTTP status class and now means
"cache status", introduce `cache_status`, don't overload `status`.
The CI gate compares PR diffs of `tag_constraints` against baseline
to flag any in-place tweak to the enumerated values of an existing
key.

## Promoting an informal metric

If a metric started out hand-emitted with a raw-string name and no
`MetricDef`:

1. Introduce the `MetricDef` via the right constructor.
2. Migrate the call sites to the new helper.
3. The pre-schema name is treated as `version=1`; if the `MetricDef`
   identity matches what the code was already emitting, no `.v2` is
   needed.

## Promoting a metric out of `correctness`

The `correctness` bucket is a signal holding bay. If a correctness
counter stays quiet for a quarter, consider deleting it (reduce
noise). If it's a routine signal the dashboard relies on, it probably
belongs in `outcome` or `resource` with a proper `.v2` migration.
