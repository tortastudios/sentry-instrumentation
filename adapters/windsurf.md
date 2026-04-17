# Windsurf

Windsurf (Codeium) uses `.windsurfrules` as always-on project
context. The adapter shape is the same as Cursor's: concatenate
`SKILL.md` plus four key references into a single rules file.

**Fast path:** `scripts/install.sh --agent=windsurf --project=<path>`
from inside the cloned skill repo. Idempotent.

## Manual install

From your project root:

```bash
# 1. Clone the skill repo for future example-file access.
git clone https://github.com/tortastudios/sentry-instrumentation \
    .windsurf/skills/sentry-instrumentation

# 2. Build a .windsurfrules file.
cat \
    .windsurf/skills/sentry-instrumentation/SKILL.md \
    .windsurf/skills/sentry-instrumentation/references/signal-model.md \
    .windsurf/skills/sentry-instrumentation/references/tagging-and-cardinality.md \
    .windsurf/skills/sentry-instrumentation/references/surface-patterns.md \
    .windsurf/skills/sentry-instrumentation/references/failure-taxonomy.md \
    > .windsurfrules
```

## How it auto-invokes

`.windsurfrules` is attached to every Windsurf Cascade + chat session
in the project. There's no trigger-based activation — the skill is
part of the default context budget.

## Testing the install

In Windsurf chat:

```text
Wrap the job-processor worker loop with instrumented_worker. Emit
enqueue / dequeue / outcome / in-flight gauge.
```

Expected: Windsurf references the queue-worker pattern from
`surface-patterns.md` and produces a wrapped loop with the right
`MetricDef` entries.

## Limitations

- No lazy-loading — the minimal install is the budget.
- For tasks that need cost-model, lifecycle, or enforcement docs,
  paste the relevant reference file into the chat on demand, or
  expand `.windsurfrules` to include it.
- Re-run the install when the skill repo updates.

## Tip: keep project rules small

If the `.windsurfrules` file starts competing with project-specific
rules, move the rarely-accessed references (cost model, emission
boundaries, review rubric) to `docs/sentry-instrumentation/` and
reference them by path in the rules file instead of inlining them.
