# Adapters

One short install guide per agent. Pick yours, follow the steps.

## Agents

| Agent | Guide | Lazy-load references? | Auto-invoke on trigger? | Minimal install? |
|---|---|---|---|---|
| Claude Code | [`claude-code.md`](claude-code.md) | yes | yes (YAML frontmatter) | no — full skill |
| Claude.ai (web) | [`claude-ai-web.md`](claude-ai-web.md) | yes | yes (YAML frontmatter) | no — full skill |
| Cursor | [`cursor.md`](cursor.md) | no | always-on | yes (~4 key references) |
| Codex | [`codex.md`](codex.md) | no | always-on | yes (SKILL.md body) |
| Aider | [`aider.md`](aider.md) | no | always-on | yes (CONVENTIONS.md) |
| Continue | [`continue.md`](continue.md) | no | always-on or slash-command | yes (`.continuerules`) |
| Windsurf | [`windsurf.md`](windsurf.md) | no | always-on | yes (`.windsurfrules`) |

## What "lazy-load" means

Claude Code + Claude.ai honor the Anthropic skill format — `SKILL.md`
loads up front, references and examples load on demand. Other agents
today don't have a standardized way to lazy-load, so the adapter
instructions for those specify a **minimal install** of the most-
read docs to keep context small:

1. `SKILL.md` (the contract)
2. `references/signal-model.md` (constructors)
3. `references/tagging-and-cardinality.md` (tag rules)
4. `references/surface-patterns.md` (drop-in patterns)
5. `references/failure-taxonomy.md` (`FailureClass`)

The other 8 references (`charter`, `metric-classes`, `semantic-
rules`, `naming-and-lifecycle`, `cost-model`, `emission-boundaries`,
`enforcement`, `review-rubric`) can be loaded on demand when the
task calls for them.

## Testing an install

After installing, prompt your agent with:

```text
What is MetricDef.failure_counter and when should I use it?
```

If the answer cites this skill's `FailureClass` taxonomy and
mentions `emit_failure(metric, failure=classify(exc), tags=...)`,
the install is working. If the answer is generic "use
sentry_sdk.metrics.count" advice, the skill didn't load — re-check
the adapter's install steps.
