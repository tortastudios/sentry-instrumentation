# Sentry Instrumentation — a governed observability skill for AI coding agents

> Your AI agent writes correct, governed Sentry instrumentation on the
> first try — across every service it touches.

**License:** MIT · **Language (v0.1):** Python (TypeScript + Go on
the roadmap) · **Works with:** Claude Code · Claude.ai · Cursor ·
Codex · Aider · Continue · Windsurf

---

## Why this exists

Most codebases have observability that grew by accident. Someone
adds a counter. Someone else adds a gauge with the same name but a
different unit. Nobody writes down what `attempt_count` actually
measures. Six months later the dashboards say the system is fine
and the SREs know it isn't.

This skill fixes that at the source. It teaches AI coding agents a
small, enforceable grammar for metrics: **one way to name them, one
way to tag them, one way to emit them, one way to retire them.** Your
agent writes the observability layer the same way every time, across
every surface (HTTP routes, external API clients, workflow steps,
retry loops, fallback paths).

**We use this in production at Torta Studios.** Every metric that
ships goes through this gate. The skill is reverse-engineered from
the patterns that actually work — not a greenfield proposal.

---

## What you get, concretely

Drop this skill into your agent and prompt it with an instrumentation
task. The output is a staff+-level observability layer that produces:

- **SLA and uptime** — derived from counters with a closed failure
  taxonomy, not free-form error strings. `failure_class="timeout"` is
  a value an alert rule can match on; `failure_class="AttributeError:
  'NoneType' object..."` is a unique series per stack frame.
- **p50/p95/p99 latency** per endpoint, per workflow step, per
  external API — all measured at canonical boundaries (middleware,
  decorator, base class). Same boundary convention in every service.
- **Cost attribution** — resource counters for LLM tokens, third-
  party API quota units, bytes written. Tells you where the bill
  went, with a tag dimension that's always a closed enumeration.
- **Bottleneck visibility** — latency distributions tagged by stage
  so you can see which step of a workflow dominates, and a separate
  duration metric per external dependency so you can see which one
  blocks the pipeline.
- **Failure intelligence** — one closed taxonomy (`TIMEOUT`,
  `AUTH_FAILURE`, `QUOTA_EXHAUSTED`, `VALIDATION_FAILURE`,
  `RATE_LIMITED`, `DEPENDENCY_FAILURE`, `INTERNAL_ERROR`, `UNKNOWN`,
  …) that alerts can match on. No more `str(exc)` leaking into tag
  values. The `UNKNOWN` bucket is its own SLI — rising `UNKNOWN`
  rate means a new exception shape showed up.
- **Retry and fallback observability** — so you know whether your
  resilience code is actually firing, and why. Attempt bucket +
  terminal outcome per retry loop; enumerated reason per fallback.

Downstream, that unlocks:

- Real SLOs (not vibes).
- Sentry bill that doesn't explode as you add services.
- Alert rules that match on stable values, not PR-specific string
  fragments.
- Post-incident queries that return something useful six months
  later.
- A code review rubric everyone can walk the same way.

---

## What's in the box

```
sentry-instrumentation/
├── SKILL.md                      # the contract your agent reads
├── references/                   # 12 deep-dive docs (~100 lines each)
│   ├── charter.md                # six universal rules
│   ├── signal-model.md           # MetricDef schema + 5 constructors
│   ├── metric-classes.md         # 5 purposes (outcome/latency/load/…)
│   ├── semantic-rules.md         # counter vs gauge vs distribution
│   ├── naming-and-lifecycle.md   # .v2 versioning + retired_at
│   ├── tagging-and-cardinality.md  # closed sets + bucket functions
│   ├── cost-model.md             # sampling + rate-limit + aggregation
│   ├── emission-boundaries.md    # where metrics belong
│   ├── failure-taxonomy.md       # FailureClass + classify()
│   ├── surface-patterns.md       # 6 drop-in patterns
│   ├── enforcement.md            # 13-check CI gate + test gates
│   └── review-rubric.md          # PR checklist
├── examples/python/              # canonical reference implementation
│   ├── metric_def.py             # MetricDef + 5 constructors
│   ├── metric_tags.py            # 5 bucket functions
│   ├── failure_taxonomy.py       # FailureClass + classify + register
│   ├── emission_module.py        # init_sentry + emit_* + aggregators
│   ├── http_middleware.py        # ObservabilityMiddleware (Starlette)
│   ├── external_api_client.py    # InstrumentedHttpClient (httpx)
│   ├── workflow_decorator.py     # @instrumented_step
│   ├── retry_loop.py             # retry_with_instrumentation
│   ├── fallback_path.py          # record_fallback
│   ├── ci_gate.py                # 13-check AST gate
│   └── test_gates.py             # pytest contract cases
└── adapters/                     # per-agent install notes
    ├── claude-code.md  · claude-ai-web.md  · cursor.md
    ├── codex.md        · aider.md          · continue.md
    └── windsurf.md
```

Lazy loading: `SKILL.md` is the only file your agent loads up front.
References and examples load on demand, only for the task at hand.

---

## The five categories, in plain language

1. **Charter.** Six universal rules every metric must obey
   (semantically precise, bounded, enforceable, versioned, cost-aware,
   ergonomic). Rejecting raw strings as tag values isn't a style
   preference — it's a dashboard-bankruptcy prevention rule.

2. **Signal model.** Every metric is a `MetricDef` with fixed fields
   (name, kind, unit, purpose, tags, cost shape, lifecycle). You
   build them through five constructors — `counter`, `latency`,
   `gauge`, `resource`, `failure_counter` — each of which fills in
   the cross-cutting fields so the call site only specifies what
   actually varies.

3. **Cost model.** Every metric declares `sampling_rate`,
   `max_rate_hz`, `loop_policy`. Hot-path distributions sample. Loops
   aggregate. Bursts get capped. Your Sentry bill stays predictable
   — a counter inside a 10,000-iteration loop emits once, not 10,000
   times.

4. **Surface patterns.** Six canonical places metrics belong (HTTP
   route, external API client, workflow step, retry loop, fallback
   path, queue worker) each have a drop-in pattern (middleware /
   decorator / base class). Using the pattern is always less code
   than hand-rolling. A new HTTP route gets instrumentation by
   mounting the middleware, not by copy-pasting three `emit_*` calls
   into the handler.

5. **Enforcement.** 13-check CI gate + runtime validators + test
   gates + a PR review rubric. The rules aren't aspirational — they
   block merge. An `emit_counter("cache.hit", ...)` with a raw
   string fails the gate before review.

Each category has one or two reference docs. Each doc is ~100 lines.
Your agent reads only the reference it needs for the current task.

---

## Quick start

### Pick your agent

| Agent | Install guide |
|---|---|
| Claude Code | [`adapters/claude-code.md`](adapters/claude-code.md) |
| Claude.ai (web) | [`adapters/claude-ai-web.md`](adapters/claude-ai-web.md) |
| Cursor | [`adapters/cursor.md`](adapters/cursor.md) |
| Codex | [`adapters/codex.md`](adapters/codex.md) |
| Aider | [`adapters/aider.md`](adapters/aider.md) |
| Continue | [`adapters/continue.md`](adapters/continue.md) |
| Windsurf | [`adapters/windsurf.md`](adapters/windsurf.md) |

Each adapter is ~30 lines: install command, invocation shape,
limitations, how to test the install.

### Scaffold your project (one-time)

Your project will end up with something like:

```
yourapp/
├── observability.py              # emission helpers + init_sentry
├── shared/
│   ├── metrics.py                # MetricDef registry
│   ├── metric_tags.py            # bucket functions
│   └── failure_taxonomy.py       # FailureClass + classify
├── middleware/observability.py   # HTTP middleware
└── services/.../instrumentation.py   # workflow step decorator
scripts/check_metrics.py          # CI gate
```

Copy the matching file from `examples/python/` to each target path;
rename `yourapp` to your package name.

### Invoke the skill

Try any of these prompts with your agent:

```text
Add governed Sentry instrumentation to the new /users endpoint.

Instrument the external Stripe client with the standard triad
(count + duration + failure).

Add a fallback counter for the case where the LLM response parse
fails.

This workflow step has no instrumentation — wrap it with
@instrumented_step and add the right MetricDef entries.

Review this PR for instrumentation quality against the skill's
review rubric.

Port the instrumentation layer we have in the Python service to the
TypeScript service — same shapes, idiomatic names.
```

Your agent will read `SKILL.md`, pick the right constructor, use the
right surface pattern, and produce code that passes the CI gate.

---

## CI gate — what it blocks

The gate ships as `examples/python/ci_gate.py`. Wire it into your
check loop (`make check`, `npm run lint`, `pre-commit`, GitHub
Actions, GitLab CI). It's AST-based, not regex-based — it won't be
fooled by unusual formatting or line splits.

Sample output on a bad PR:

```text
$ python scripts/check_metrics.py \
    --registry yourapp/shared/metrics.py \
    --emission-module yourapp/observability.py \
    --project-root yourapp

yourapp/services/orders.py:42: M002: emit_counter first arg must be
  a MetricDef symbol; got f-string.
yourapp/shared/metrics.py:115: M006: cardinality="medium" requires a
  justification in means=.
yourapp/workers/retry.py:88: M012: emit_counter inside for-body
  requires AggregatingCounter or escape comment.
✗ 3 violations. Merge blocked.
```

The 13 checks are listed in `references/enforcement.md` as portable
principles — your TS/Go port can apply the same rules with different
tools (`ts-morph` / `ast-grep`, `go/ast`). Keep the check identifiers
(M001…M013) consistent across ports so reviewers can reference them
identically.

---

## Gotchas

- **Identity is immutable.** Changing a metric's meaning = new name
  with a `.v2` suffix + 14-day overlap + `retired_at`. No silent
  renames. A rename breaks every dashboard and alert rule at once.
- **No raw exception strings as tag values.** Use `classify(exc)` →
  one of ~9 `FailureClass` values. The `UNKNOWN` bucket is a
  feature, not a bug — its rate is its own SLI.
- **Distributions on hot paths must sample** (`sampling_rate < 1.0`).
  Loops must aggregate (`AggregatingCounter` / `DurationAccumulator`).
- **This skill is Sentry-first.** Product analytics (funnel events,
  button clicks) don't belong here — they go in a sibling PostHog
  skill.
- **Sentry Metrics API caveats.** The examples use the
  `sentry_sdk.metrics.count/gauge/distribution` API. Sentry Metrics
  has moved through beta — pin `sentry-sdk>=2.0` and re-verify the
  call surface against your SDK version. See
  `examples/python/README.md` for the tested version.
- **Python 3.11+ for the reference examples** (`StrEnum`, union type
  syntax `X | Y`). TS/Go ports coming in v0.2.

---

## Roadmap — work in progress

- **v0.1** (you are here): Python canonical reference. Seven agent
  adapters. MIT license. Production-tested.
- **v0.2**: TypeScript/Node port (emission module + HTTP middleware
  + one external-API client + test gates).
- **v0.3**: Go port. Multi-CI workflow templates
  (`ci/github-actions.yml`, `ci/gitlab-ci.yml`, pre-commit hook).
- **Backlog**: Ruby, Java, Rust ports. OpenTelemetry adapter (so the
  same `MetricDef` targets OTel Metrics alongside Sentry).
  Auto-generated registry docs. Sibling `sentry-tracing` skill for
  spans.

---

## Contributing

- Open an issue with your language + framework and what's missing.
- PRs welcome for adapter files (`adapters/<agent>.md`) and for
  porting `examples/python/` patterns to other languages.
- New `FailureClass` values require a design discussion — they break
  every downstream dashboard that filters on the taxonomy.
- Reference-doc rewrites and clarifications always welcome.

---

## License

MIT. Copyright © 2026 Torta Studios. See [LICENSE](LICENSE).

## Credits

Reverse-engineered from production observability at **Torta
Studios**. The skill ships instrumentation patterns — not
proprietary business logic.
