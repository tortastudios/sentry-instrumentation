# Codex

Codex honors `AGENTS.md` files — project-scoped instruction files the
model reads as context. The adapter pattern is to include a pointer
to this skill in your `AGENTS.md`, plus the `SKILL.md` body inline
for full context.

## Install

From your project root:

```bash
# 1. Clone the skill somewhere findable by both you and Codex.
git clone https://github.com/tortastudios/sentry-instrumentation \
    .agents/skills/sentry-instrumentation

# 2. Add a section to your project's AGENTS.md.
cat >> AGENTS.md <<'EOF'

## Sentry instrumentation

This project uses the `sentry-instrumentation` governed-observability
skill. When writing code that emits a Sentry metric, measures
duration, counts failures, wraps a workflow step, or adds a retry /
fallback path:

1. Read `.agents/skills/sentry-instrumentation/SKILL.md`.
2. Follow the decision rules and surface patterns documented there.
3. When the task calls for deeper rules (tagging, cost model,
   lifecycle), open the referenced file in
   `.agents/skills/sentry-instrumentation/references/`.
4. Use `.agents/skills/sentry-instrumentation/examples/python/`
   as the canonical drop-in reference.

Never hand-roll emissions — use the surface patterns (middleware,
decorator, base class). Never pass a raw string to an emit helper.
EOF
```

If you prefer to inline the skill body (so Codex doesn't need the
extra file open), append the contents of `SKILL.md` directly after
the pointer.

## How it auto-invokes

Codex reads `AGENTS.md` at session start. When your prompt matches
the conditions in the skill section, Codex follows the decision
rules. There's no lazy-load — the `AGENTS.md` contents are always
loaded.

## Testing the install

Prompt Codex with:

```text
Instrument the webhook handler with the standard HTTP triad.
```

Expected: Codex mounts `ObservabilityMiddleware` (or extends an
existing one), doesn't hand-roll three `emit_*` calls in the
handler, and references the skill's surface patterns.

## Limitations

- `AGENTS.md` context weight — if the file grows large, the skill
  section becomes one of several instruction blocks competing for
  attention. Keep it at the top of `AGENTS.md`.
- No automatic reference-loading — reviewers have to ask Codex to
  "check `references/<doc>.md`" when a task needs a specific rule.
