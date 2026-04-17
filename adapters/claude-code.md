# Claude Code

Claude Code auto-discovers skills via YAML frontmatter. Installation
is a clone into the skills directory.

## Fast path

From inside the cloned skill repo:

```bash
scripts/install.sh --agent=claude-code                            # user-level
scripts/install.sh --agent=claude-code --project=/path/to/project # project-level
```

Idempotent — symlinks the skill-clone into `~/.claude/skills/` (or
`<project>/.claude/skills/`). If the symlink already points at the right
target, it's a no-op. Equivalent to the manual `git clone` below.

## Install (user-level — available in every project)

```bash
git clone https://github.com/tortastudios/sentry-instrumentation \
    ~/.claude/skills/sentry-instrumentation
```

## Install (project-level — versioned with the repo)

```bash
cd path/to/your/project
git clone https://github.com/tortastudios/sentry-instrumentation \
    .claude/skills/sentry-instrumentation
```

Or add as a git submodule if you want pinned versions:

```bash
git submodule add https://github.com/tortastudios/sentry-instrumentation \
    .claude/skills/sentry-instrumentation
```

## How it auto-invokes

Claude Code reads the `description:` field in `SKILL.md` frontmatter
at session start. When your prompt contains triggers ("instrument",
"add a counter", "observe", "track system behavior", or any of the
conditions in the description), the skill loads automatically. No
manual `/sentry-instrumentation` invocation needed.

## What loads when

- `SKILL.md` — always, at session start.
- `references/*.md` — on-demand, when the task references them.
- `examples/python/*.py` — on-demand, when the task calls for a
  drop-in.

This is the full-fidelity experience the skill was designed around.

## Testing the install

Open a Claude Code session in any project and run:

```text
What's the right MetricDef constructor for a counter that tracks
how many tokens we consumed from the LLM provider?
```

The expected answer names `MetricDef.resource(...)` with `unit="tokens"`.
If you get a generic `sentry_sdk.metrics.count(...)` reply, the skill
didn't load — check that `~/.claude/skills/sentry-instrumentation/
SKILL.md` exists.

## Limitations

None known. Claude Code is the reference environment for this skill.
