# Agents guide — sentry-instrumentation

## What this repo is

`sentry-instrumentation` is an **Anthropic-format skill**: a set of rules,
references, and drop-in code patterns that teach AI coding agents how to
add Sentry metrics the right way. The canonical reference ships in Python
under `examples/python/`, but the patterns are language-neutral and port
to TypeScript, Go, Ruby, etc. The skill is production-tested at Torta
Studios.

This is not an application. There is nothing to run from this repo — it
is installed *into* consumer projects so that an AI agent working in
those projects reads its rules.

## This repo has no "skill registry"

There is no cross-agent "skill registry file" standard. Each supported
agent discovers skills its own way:

| Agent | Discovery file |
|---|---|
| Claude Code | `SKILL.md` YAML frontmatter under `~/.claude/skills/` or `.claude/skills/` |
| Claude.ai (web) | `SKILL.md` YAML frontmatter uploaded via Settings → Skills |
| Codex | `AGENTS.md` at project root |
| Cursor | `.cursor/rules/*.mdc` |
| Aider | `CONVENTIONS.md` (or any file passed via `--read`) |
| Continue | `.continuerules` |
| Windsurf | `.windsurfrules` |

The install shape for each agent lives under `adapters/<agent>.md`. The
matrix is in [`adapters/README.md`](adapters/README.md).

## If you're a Codex agent asked to install this skill

One command, from inside the cloned skill repo:

```bash
scripts/install.sh --agent=codex --project=/path/to/consumer/project
```

That appends the **Skill-enable block** below into the consumer project's
`AGENTS.md`, bracketed by marker comments so re-runs update in place.

If you prefer to do it by hand, copy the block below into the consumer
project's `AGENTS.md`, and adjust the paths to point at the cloned skill
on disk.

## Skill-enable block (copy into consumer `AGENTS.md`)

```markdown
<!-- BEGIN sentry-instrumentation -->
## Sentry instrumentation

This project uses the `sentry-instrumentation` skill. When writing code
that emits a Sentry metric, measures duration, counts failures, wraps a
workflow step, or adds a retry or fallback path:

1. Read `<path-to-skill>/SKILL.md`.
2. Follow its decision rules and surface patterns.
3. For deeper rules (tagging, cost model, lifecycle), open the relevant
   file under `<path-to-skill>/references/`.
4. Use `<path-to-skill>/examples/python/` as the canonical drop-in
   reference.

Never hand-roll emissions — use the surface patterns (middleware,
decorator, base class). Never pass a raw string to an emit helper.
<!-- END sentry-instrumentation -->
```

Replace `<path-to-skill>` with wherever the skill is cloned on disk
(typical: `.agents/skills/sentry-instrumentation/` inside the consumer
project, or an absolute path under `~/`). The install script resolves
this automatically.

## Other agents

- **Claude Code** — `scripts/install.sh --agent=claude-code` symlinks
  this repo into `~/.claude/skills/` (or `.claude/skills/` with
  `--project=<path>`). See [`adapters/claude-code.md`](adapters/claude-code.md).
- **Claude.ai (web)** — not scriptable; upload via Settings → Skills.
  See [`adapters/claude-ai-web.md`](adapters/claude-ai-web.md).
- **Cursor / Aider / Continue / Windsurf** — `scripts/install.sh
  --agent=<name> --project=<path>` writes the rules file each agent
  discovers. See the matching `adapters/<agent>.md`.

## Why the installer exists

The rules file most non-Anthropic agents expect is a single concatenated
blob (`SKILL.md` plus a handful of high-value references). Doing that by
hand works once — every skill update then requires re-running a fragile
`cat` pipeline. `scripts/install.sh` is idempotent: re-running after an
upstream update refreshes the install in place.
