# Cursor

Cursor uses `.cursor/rules/*.mdc` files as always-on context. It
doesn't lazy-load, so the adapter concatenates `SKILL.md` plus four
high-value references into a single rule file. That keeps context
small while covering the ~80% of instrumentation questions.

## Install

From your project root:

```bash
mkdir -p .cursor/rules
cat > .cursor/rules/sentry-instrumentation.mdc <<'EOF'
---
description: Governed Sentry instrumentation — see sentry-instrumentation skill
globs: **/*.py
alwaysApply: true
---
EOF

# Then append the skill content. From the cloned skill repo:
cat \
    path/to/sentry-instrumentation/SKILL.md \
    path/to/sentry-instrumentation/references/signal-model.md \
    path/to/sentry-instrumentation/references/tagging-and-cardinality.md \
    path/to/sentry-instrumentation/references/surface-patterns.md \
    path/to/sentry-instrumentation/references/failure-taxonomy.md \
    >> .cursor/rules/sentry-instrumentation.mdc
```

Adjust the `globs:` line to your language (`**/*.{ts,tsx}` for
TypeScript, `**/*.go` for Go).

## What this covers

The four included references carry the core contracts: the
`MetricDef` schema, tag rules, surface patterns, and failure
taxonomy. When a task calls for cost-model, emission-boundary, or
lifecycle knowledge that isn't in this minimal install, the best
move is to switch to Claude Code for that task, or temporarily
include the extra reference file.

## How it auto-invokes

`alwaysApply: true` means the rule is attached to every Cursor
conversation in this project. Cursor has no equivalent of Claude
Code's frontmatter-based auto-invocation, so the skill is always
part of the context budget.

## Testing the install

In Cursor chat, prompt:

```text
Add governed Sentry instrumentation to the POST /orders endpoint.
Use the skill's surface patterns.
```

Cursor should reference `ObservabilityMiddleware`, recommend
`MetricDef.counter(...)` / `MetricDef.latency(...)`, and avoid raw
`emit_counter("orders.created", ...)` calls.

## Limitations

- No lazy-loading — the minimal install is 5 files concatenated. If
  your `.cursor/rules/` context gets tight, drop
  `surface-patterns.md` first (it's the longest).
- No skill-version awareness — re-run the install when the GitHub
  repo updates.
