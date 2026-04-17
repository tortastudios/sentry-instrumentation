# PR review rubric

Walk this list for any PR that touches instrumentation. Copy into the
PR template or a local checklist.

## Kind and shape

1. **Right `kind` for the meaning?**
   - Counting discrete events → `counter`.
   - Sampled duration → `distribution` (via `MetricDef.latency`).
   - Currently-occupied quantity → `gauge`.
2. **Name matches the contract?**
   - `<domain>.<object>.<action>[.<type-suffix>]`, lowercase, dotted.
   - No runtime concatenation — literal string.
   - Fits one of the five `purpose` values.

## Tagging

3. **All tag keys in `MetricDef.allowed_tags`?**
4. **All tag values enumerated in `tag_constraints` or produced by an
   approved bucket function?**
5. **No forbidden values?** (user ids, URLs, raw exception strings,
   timestamps, versioned model names, IPs, file paths)

## Duplication

6. **Duplicative with an existing `MetricDef`?** Grep the registry
   before adding. If a similar metric already exists, extend it (if
   the identity tuple fits) or version it (`.v2`) with a migration
   plan — don't invent a parallel name.

## Operational clarity

7. **`operational_meaning` unambiguous?** Ask: will somebody reading
   this metric in six months, without PR context, know what it
   measures, where the boundary is, and how to derive the useful
   ratio?

## Cardinality

8. **If `cardinality="medium"`:** is the justification credible? Does
   `means=` spell out why the dimensional explosion is worth the
   series cost? Would a log line or span be a better fit?

## Failure metrics

9. **Failure metric uses `emit_failure(...)`?** Not `emit_counter` with
   a hand-rolled `failure_class` tag.
10. **Every exception site that can reach this counter has a
    `register(Exc, FailureClass.X)` call?** Otherwise the `UNKNOWN`
    bucket will catch it — that's sometimes acceptable, but confirm
    it's intentional.

## Cost

11. **High-frequency path → `sampling_rate` / `max_rate_hz` set?**
12. **Inside a loop → uses `AggregatingCounter` /
    `DurationAccumulator`?** Or has the `# instrumentation: loop-aggregate`
    escape comment with a rationale the reviewer accepts?

## Emission boundary

13. **Emitted at a documented boundary** (request lifecycle, workflow
    step, external call, retry, fallback) or via a canonical surface
    pattern (middleware, decorator, base class)?
14. **Not emitted inside a helper that has a single caller?** Move
    the emission up.

## Lifecycle

15. **Changing an existing metric?** Confirm it's actually a new
    versioned entry (`.v2`) with:
    - Old entry marked `deprecated=True`, `replaced_by="<new>"`,
      `retired_at=<today + 14 days>`.
    - Both emitting during overlap.
    - A follow-up PR scheduled to remove the old entry.
16. **Removing an entry?** Confirm it was already `deprecated=True`
    in a prior PR. Silent removal fails CI.

## Test coverage

17. **Contract-level test gates still green?** The gates (see
    `examples/python/test_gates.py` for the reference) cover the new
    `MetricDef`.
18. **A new bucket function?** Add parametric tests covering its
    enumeration and pathological inputs (negatives, zero, huge
    values) — each bucket must be total.

## Anti-patterns to flag

- Raw string passed to any `emit_*` call.
- Raw exception type or message in a tag value.
- Dynamic metric name (f-string, `.format`, variable).
- Distribution used to record integer counts.
- Gauge used for monotonic accumulation.
- `emit_counter` inside a `for` body without an aggregator.
- `allowed_tags` expanded without adding the matching entry in
  `tag_constraints`.
- New `FailureClass` value added with no follow-up to update
  downstream dashboards.
