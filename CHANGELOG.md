# Changelog

All notable changes to the `sentry-instrumentation` skill are documented
here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
version numbers follow [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- TypeScript / Node reference implementation (`examples/typescript/`).
- `adapters/continue.md` + `adapters/windsurf.md` field-testing.
- `ci/` workflow templates for GitHub Actions, GitLab CI, pre-commit.

## [1.1.0] — 2026-04-24

Progressive-disclosure refactor of `SKILL.md`. Hot-path bytes — the content
the agent reads on every skill invocation — shrink from 224 lines / 11.8 KB
to 69 lines / 5.6 KB (≈53% reduction) without removing any decision-driving
content. Deep rules stay in `references/` and load only when the task asks
for them. No behavior change for agents that follow the decision rules; no
change to the `MetricDef` schema, the Python examples, the CI gate, or the
installer command-line interface.

### Changed

- **`SKILL.md`** restructured as a lean dispatcher. Kept: YAML frontmatter
  with auto-invocation triggers, the six decision rules, language-detection
  hint, Python project-path table, and the reference index.
- **`scripts/install.sh`** `MINIMAL_CONCAT_FILES` expanded from 5 files to 7.
  `references/charter.md` and `references/review-rubric.md` are now inlined
  into the single rules file emitted for Cursor, Aider, Continue, and
  Windsurf, so agents that cannot lazy-load references still see the charter
  principles and the PR-review rubric. Claude Code continues to use the
  symlink install and benefits from the leaner `SKILL.md`.

### Removed (from `SKILL.md` only — no information lost)

- **Charter restatement** — the full version already lives in
  `references/charter.md`, linked from the reference index.
- **"When this skill applies" section** — duplicated the YAML
  `description:` field's auto-invocation triggers.
- **TypeScript and Go project-path tables** — placeholders for ports
  that have not shipped. Will be re-introduced alongside
  `examples/typescript/` (v0.2) and `examples/go/` (v0.3).
- **Quality-gate checklist** — the full version already lives in
  `references/review-rubric.md`, linked from the reference index.

### Rationale

Anything that loads on every skill invocation — every `SKILL.md` byte —
competes with the task itself for the model's attention and token budget.
The deleted sections were either duplicates of content the agent can
retrieve on demand, or placeholders for languages without shipped
references. Moving them out of the hot path shortens the preamble, lets the
model spend more attention on the actual coding task, and keeps the
progressive-disclosure boundary clean: `SKILL.md` decides *which* reference
to open; `references/` carries the depth.

## [1.0.0] — 2026-04-17

Stable release. Same content as 0.1.0; promoted to 1.0.0 to signal API
stability so downstream projects can pin the skill (`git checkout v1.0.0`
or `git submodule add -b v1.0.0 ...`) without expecting breaking changes
to SKILL.md, the reference docs, the Python example modules, the CI gate,
or the installer interface.

## [0.1.0] — 2026-04-17

Initial open-source release. Python canonical reference, production-tested at
Torta Studios.

### Added

- **SKILL.md** — language-aware skill contract with Anthropic frontmatter,
  auto-invocation triggers, decision rules, and quality-gate checklist.
- **12 reference docs** (`references/`): charter, signal-model, metric-classes,
  semantic-rules, naming-and-lifecycle, tagging-and-cardinality, cost-model,
  emission-boundaries, failure-taxonomy, surface-patterns, enforcement,
  review-rubric.
- **Python reference implementation** (`examples/python/`) — 11 drop-in
  modules: `metric_def.py`, `metric_tags.py`, `failure_taxonomy.py`,
  `emission_module.py`, `http_middleware.py`, `external_api_client.py`,
  `workflow_decorator.py`, `retry_loop.py`, `fallback_path.py`, `ci_gate.py`,
  `test_gates.py`.
- **Seven installation adapters** (`adapters/`): Claude Code, Claude.ai web,
  Cursor, Codex, Aider, Continue, Windsurf.
- **CI gate** with 13 AST-based checks enforcing metric identity, naming,
  tagging, lifecycle, cardinality, loop policy, and dynamic-name rules.
- **README.md** — value pitch, quick start, category overview, CI gate demo,
  gotchas, roadmap.
- **MIT LICENSE** — copyright 2026 Torta Studios.

### Notes

- Tested against `sentry-sdk>=2.0` (Python) as of April 2026. Sentry Metrics
  is still in open beta and has had pricing/API churn; pin an SDK version
  and watch Sentry's changelog.
- Python 3.11+ required for the reference examples (`StrEnum`, union type
  syntax).
