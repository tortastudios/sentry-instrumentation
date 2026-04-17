# Changelog

All notable changes to the `sentry-instrumentation` skill are documented
here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
version numbers follow [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- TypeScript / Node reference implementation (`examples/typescript/`).
- `adapters/continue.md` + `adapters/windsurf.md` field-testing.
- `ci/` workflow templates for GitHub Actions, GitLab CI, pre-commit.

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
