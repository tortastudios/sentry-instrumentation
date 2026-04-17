# Continue

Continue supports persistent project context via `.continuerules` and
custom slash commands. The adapter uses both: `.continuerules` for
always-on context, plus a `/sentry-instrument` slash command for
explicit invocation.

**Fast path:** `scripts/install.sh --agent=continue --project=<path>`
from inside the cloned skill repo writes `.continuerules`. Idempotent.
The custom slash command still needs a manual config edit — see below.

## Install (minimal — always-on)

From your project root:

```bash
# 1. Clone the skill repo for example-file access.
git clone https://github.com/tortastudios/sentry-instrumentation \
    .continue/skills/sentry-instrumentation

# 2. Build a .continuerules file.
cat \
    .continue/skills/sentry-instrumentation/SKILL.md \
    .continue/skills/sentry-instrumentation/references/signal-model.md \
    .continue/skills/sentry-instrumentation/references/tagging-and-cardinality.md \
    .continue/skills/sentry-instrumentation/references/surface-patterns.md \
    .continue/skills/sentry-instrumentation/references/failure-taxonomy.md \
    > .continuerules
```

## Install (full — with a slash command)

Edit `.continue/config.json` (or `config.yaml`) and add a custom
slash command:

```json
{
  "customCommands": [
    {
      "name": "sentry-instrument",
      "description": "Add governed Sentry instrumentation using the sentry-instrumentation skill.",
      "prompt": "Read the full sentry-instrumentation skill at .continue/skills/sentry-instrumentation/SKILL.md and references/. Apply its decision rules and surface patterns to: {{ input }}"
    }
  ]
}
```

Now `/sentry-instrument add a counter for cache hits` invokes the
skill explicitly with the full context budget.

## How it auto-invokes

- `.continuerules` contents are attached to every Continue completion
  in the project.
- The slash command is explicit — invoke it when the task needs the
  full skill (cost model, lifecycle rules, all references).

## Testing the install

```text
/sentry-instrument instrument the external Stripe client
```

Expected: Continue suggests extending `InstrumentedHttpClient` with
a `StripeClient` subclass, registers the dependency-call triad, and
maps Stripe-specific exceptions to `FailureClass` values.

## Limitations

- No lazy-loading — the `.continuerules` minimal install is
  always-on.
- The slash command pulls the full skill only if the clone path is
  reachable from the workspace.
- Re-build `.continuerules` when the skill repo updates.
