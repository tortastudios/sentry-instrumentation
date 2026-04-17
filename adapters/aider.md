# Aider

Aider reads `CONVENTIONS.md` (or any file passed via `--read`) as
persistent context. The adapter is: include `SKILL.md` + the key
references as a `CONVENTIONS.md` file and pass it on the command
line.

## Install

From your project root:

```bash
# 1. Clone the skill so Aider can reference its example files later.
git clone https://github.com/tortastudios/sentry-instrumentation \
    .aider-skills/sentry-instrumentation

# 2. Build a CONVENTIONS.md that Aider will load on every run.
cat \
    .aider-skills/sentry-instrumentation/SKILL.md \
    .aider-skills/sentry-instrumentation/references/signal-model.md \
    .aider-skills/sentry-instrumentation/references/tagging-and-cardinality.md \
    .aider-skills/sentry-instrumentation/references/surface-patterns.md \
    .aider-skills/sentry-instrumentation/references/failure-taxonomy.md \
    > CONVENTIONS.md

# 3. Invoke Aider with the conventions file.
aider --read CONVENTIONS.md
```

Or alias it:

```bash
alias aider-instr='aider --read CONVENTIONS.md'
```

## How it auto-invokes

Aider loads the `--read` files at session start. There's no trigger-
based activation; the skill is always part of the prompt context.

## Testing the install

```bash
$ aider --read CONVENTIONS.md

> add governed sentry instrumentation to the new /users endpoint
```

Expected: Aider mounts the observability middleware, registers new
`MetricDef` entries via the right constructor, and passes the CI
gate.

## Limitations

- `--read` files are loaded fully; there's no lazy-loading. Minimal
  install = 5 files (SKILL + 4 references).
- No automatic skill-version updates — re-run the `cat` step when the
  skill repo updates.
- For tasks that need the cost model or lifecycle docs, either load
  the extra reference via a second `--read` flag, or paste the
  relevant file contents into the chat.

## Tip: commit-hook integration

Aider supports a commit hook. You can have Aider run the skill's CI
gate locally before the commit:

```bash
aider --read CONVENTIONS.md \
      --lint-cmd "python scripts/check_metrics.py \
                  --registry yourapp/shared/metrics.py \
                  --emission-module yourapp/observability.py \
                  --project-root yourapp"
```

Failures block the commit — the skill's contract becomes enforceable
in the loop.
