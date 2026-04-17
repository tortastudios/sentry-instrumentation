# Claude.ai (web)

Claude.ai supports uploadable skills via Settings. The web app honors
the same YAML frontmatter as Claude Code, so the full skill
(references + examples lazy-loaded) works the same way.

## Install

1. Open Claude.ai → **Settings** → **Skills**.
2. Click **Add skill**.
3. Upload the whole repo as a zip, or paste the GitHub URL:

   ```
   https://github.com/tortastudios/sentry-instrumentation
   ```
4. Claude.ai parses `SKILL.md` and indexes the references + examples.

## How it auto-invokes

Same as Claude Code — the `description:` field in frontmatter is
matched against your prompt. When triggers fire, the skill loads.

## What loads when

- `SKILL.md` — always, at conversation start.
- `references/*.md` — on-demand.
- `examples/python/*.py` — on-demand.

## Testing the install

Start a new conversation and prompt:

```text
Using the sentry-instrumentation skill, explain what
emit_failure requires and why we can't just pass str(exc) as a tag.
```

Expected: a reference to `FailureClass` taxonomy and the cardinality-
blowup / PII-leak reasoning from `references/tagging-and-cardinality.md`.

## Limitations

- No local file system access, so the scaffold steps in the quick
  start (copying `examples/python/*.py` into your project) have to
  run in a separate Claude Code session, Cursor, or terminal.
- Skill-version tracking is manual — re-upload when the GitHub repo
  updates.
