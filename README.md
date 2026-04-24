# Sentry Instrumentation

> Your AI agent adds Sentry metrics the right way on the first try —
> so a year from now, when someone asks "is the app actually working?",
> you have an answer that isn't a guess.

**License:** MIT · **Language (v0.1):** Python (TypeScript + Go on
the roadmap) · **Works with:** Claude Code · Claude.ai · Cursor ·
Codex · Aider · Continue · Windsurf

---

## Why this matters

Picture this. You build something good. It gets traction. Six months
later, a real enterprise customer shows up and says:

> "We love it. We want to use it company-wide. Send us your SLA — how
> often is the app up? How fast does it respond? When things break,
> how fast do you notice?"

You now have two choices.

**Choice 1 — make up a number.** Sounds fine until the second month,
when the real number doesn't match the one in the contract, and the
customer's legal team notices. Now you have a problem that costs more
than the deal.

**Choice 2 — actually know the number.** You can pull it from real
measurements your app has been writing down since day one. You say:

> "Over the last 90 days, checkout succeeded 99.94% of the time. The
> p95 response time was 420ms. We detect any outage longer than 60
> seconds within 2 minutes, and here's the incident log proving it."

That answer only exists if your app was measuring itself correctly
from the start. This skill is what teaches your AI coding agent to do
that from day one — not as a last-minute scramble when the enterprise
deal shows up.

It's the difference between **guessing how your app is doing** and
**knowing**.

---

## What this skill actually does

Most codebases measure themselves by accident. Someone adds a counter
called `cache_hits`. Someone else adds one called `cacheHit`. A third
person adds one called `cache.hit.count` with a user ID as a tag — and
now your Sentry bill is going up 30% a month because every user makes
a new series. Nobody writes down what `attempt_count` actually means.
A year later the dashboards say the system is fine, and your on-call
engineer knows it isn't.

This skill fixes that at the source. It gives your AI coding agent a
small, strict grammar for adding metrics: **one way to name them, one
way to tag them, one way to emit them, one way to retire them.** Your
agent writes the same shapes every time, in every file, across every
surface (HTTP routes, external API clients, workflow steps, retry
loops, fallback paths).

**We use this in production at Torta Studios.** Every metric that
ships goes through this gate. The skill is reverse-engineered from
what actually works in production — not a wish list.

---

## What you get, concretely

Drop this into your AI coding agent, then ask it to add metrics to
some part of your app. What comes back is measurement code good
enough to run a business on:

- **SLA and uptime numbers you can put in a contract.** Failures are
  tagged with a short fixed list of causes (`timeout`,
  `auth_failure`, `rate_limited`, etc.) — not raw error messages. An
  alert rule can match on `timeout`. It can't match on
  `AttributeError: 'NoneType' object has no attribute 'id' at
  handlers.py:427`.
- **Real p50/p95/p99 response times** per endpoint, per workflow
  step, per external API you depend on. All measured at the same
  spots in the code (middleware, decorator, base class), so the
  numbers are comparable across services.
- **Cost attribution.** How many LLM tokens did this endpoint burn?
  How many Stripe API calls went to the wrong environment? You get
  counters for LLM tokens, third-party API quota units, bytes
  written — each with a clean, closed list of tag values so the
  numbers stay grouped sensibly.
- **Bottleneck visibility.** Latency distributions tagged by stage,
  so you can see which step of a workflow is the slow one. Separate
  duration metric per external dependency, so you can see which
  vendor is slowing you down this week.
- **Failure intelligence.** One closed list of failure causes
  (`TIMEOUT`, `AUTH_FAILURE`, `QUOTA_EXHAUSTED`,
  `VALIDATION_FAILURE`, `RATE_LIMITED`, `DEPENDENCY_FAILURE`,
  `INTERNAL_ERROR`, `UNKNOWN`, …) that alert rules can match on. The
  `UNKNOWN` bucket is on purpose — if it starts rising, a new kind
  of failure just showed up and needs a name.
- **Retry and fallback observability.** You can tell whether your
  resilience code is firing, how often, and why. Attempt bucket +
  final outcome per retry loop. Named reason per fallback path.

Downstream, once these numbers exist, you get:

- **Real SLOs** — numbers you can show a customer, not vibes.
- **A Sentry bill that doesn't balloon as you add services**, because
  the rules block the patterns that explode the bill.
- **Alert rules that match on stable values**, not on string
  fragments that change every PR.
- **Incident queries that still return something useful six months
  later**, because the metric names and tag shapes didn't drift.
- **A code-review checklist** everyone can follow the same way.

---

## What's in the repo

```
sentry-instrumentation/
├── SKILL.md                      # the short contract your agent reads first
├── references/                   # 12 deeper docs, ~100 lines each
│   ├── charter.md                # the six rules every metric must follow
│   ├── signal-model.md           # the MetricDef schema + 5 constructors
│   ├── metric-classes.md         # the 5 "purposes" a metric can have
│   ├── semantic-rules.md         # counter vs gauge vs distribution
│   ├── naming-and-lifecycle.md   # .v2 versioning + retired_at dates
│   ├── tagging-and-cardinality.md  # safe tags + bucket functions
│   ├── cost-model.md             # sampling, rate limits, aggregation
│   ├── emission-boundaries.md    # where metrics belong in the code
│   ├── failure-taxonomy.md       # the closed failure-class list
│   ├── surface-patterns.md       # 6 drop-in code patterns
│   ├── enforcement.md            # the 13-check CI gate
│   └── review-rubric.md          # the PR checklist
├── examples/python/              # Python reference implementation
│   ├── metric_def.py             # MetricDef + 5 constructors
│   ├── metric_tags.py            # bucket functions
│   ├── failure_taxonomy.py       # FailureClass + classify + register
│   ├── emission_module.py        # emit_* helpers + aggregators
│   ├── http_middleware.py        # ObservabilityMiddleware (Starlette)
│   ├── external_api_client.py    # InstrumentedHttpClient (httpx)
│   ├── workflow_decorator.py     # @instrumented_step
│   ├── retry_loop.py             # retry_with_instrumentation
│   ├── fallback_path.py          # record_fallback
│   ├── ci_gate.py                # 13-check AST gate
│   └── test_gates.py             # pytest contract cases
└── adapters/                     # one install guide per agent
    ├── claude-code.md  · claude-ai-web.md  · cursor.md
    ├── codex.md        · aider.md          · continue.md
    └── windsurf.md
```

Your agent only reads `SKILL.md` up front. References and examples
load on demand, only for the task at hand.

---

## The five ideas, in plain words

1. **Charter — the six rules.** Every metric has to be: meaningful
   (you can say what it measures in one sentence), bounded (tag
   values come from a short list, not free-form strings), enforceable
   (defined once, checked by CI), versioned (rename = new name, not
   a silent change), cost-aware (it can't explode your bill inside a
   loop), and easy to use (the right way is also the shortest way to
   type). Rejecting raw strings as tags isn't picky — it's the
   difference between a stable dashboard and one that goes to zero
   the next time someone changes an error message.

2. **Signal model — how metrics are defined.** Every metric is a
   `MetricDef` with fixed fields (name, what it measures, unit, the
   allowed tags, the cost shape, when to retire it). You build one
   through one of five shortcuts — `counter`, `latency`, `gauge`,
   `resource`, `failure_counter` — each of which fills in the boring
   fields for you, so the code at the call site only specifies what
   actually varies.

3. **Cost model — how not to blow up the bill.** Every metric
   declares how often it should fire, whether to sample on hot
   paths, and whether it's allowed inside loops. A counter inside a
   10,000-iteration loop emits **once**, not 10,000 times. Bursts
   get capped. Your Sentry bill stays predictable as the app grows.

4. **Surface patterns — drop-in code for the six common places.**
   HTTP route, external API client, workflow step, retry loop,
   fallback path, queue worker. Each has a reusable pattern
   (middleware, decorator, base class). Using the pattern is always
   less code than hand-rolling three `emit_*` calls. A new HTTP
   route gets instrumentation by mounting the middleware, not by
   copy-pasting emission code into every handler.

5. **Enforcement — this is checked, not suggested.** A 13-check CI
   gate + runtime validators + test contracts + a PR review checklist.
   The rules aren't aspirational. An `emit_counter("cache.hit", ...)`
   with a raw string fails the check and blocks the merge.

Each idea has one or two reference docs. Each doc is about 100 lines.
Your agent reads only the one it needs for the current task.

---

## Quick start

### One-command install (all agents except Claude.ai web)

```bash
git clone https://github.com/tortastudios/sentry-instrumentation.git
cd sentry-instrumentation
scripts/install.sh --agent=<agent> --project=/path/to/your/project
```

`<agent>` is one of: `claude-code` · `cursor` · `codex` · `aider` ·
`continue` · `windsurf`. Idempotent — safe to re-run after upstream
updates. For Claude Code the `--project` flag is optional (leave it
off for a user-level install in `~/.claude/skills/`).

### Pin a version

To lock to a stable release, check out a tag before running the
installer:

```bash
git clone https://github.com/tortastudios/sentry-instrumentation.git
cd sentry-instrumentation
git checkout v1.1.0
scripts/install.sh --agent=<agent> --project=/path/to/your/project
```

Or add as a pinned submodule:

```bash
git submodule add -b v1.1.0 \
  https://github.com/tortastudios/sentry-instrumentation.git \
  vendor/sentry-instrumentation
```

Available tags: `git ls-remote --tags https://github.com/tortastudios/sentry-instrumentation.git`.

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

Each adapter is ~30 lines: the install command, how it shows up in
your agent's context, what to watch out for, and how to test that
the install actually worked.

### Scaffold your project (one-time)

Your project will end up with files roughly like this:

```
yourapp/
├── observability.py              # emission helpers + init_sentry
├── shared/
│   ├── metrics.py                # the MetricDef registry
│   ├── metric_tags.py            # bucket functions
│   └── failure_taxonomy.py       # FailureClass + classify
├── middleware/observability.py   # HTTP middleware
└── services/.../instrumentation.py   # workflow step decorator
scripts/check_metrics.py          # CI gate
```

Copy the matching file from `examples/python/` to each spot, then
rename `yourapp` to your actual package name.

### Try the skill

Paste any of these prompts into your agent:

```text
Add Sentry instrumentation to the new /users endpoint.

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

## The CI gate — what it blocks

The gate ships as `examples/python/ci_gate.py`. Wire it into your
check loop (`make check`, `npm run lint`, `pre-commit`, GitHub
Actions, GitLab CI — wherever you already run tests). It reads the
actual Python syntax tree, so it doesn't get fooled by weird line
breaks or formatting.

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
rules — your TypeScript or Go port can apply the same rules with
different tools (`ts-morph` / `ast-grep`, `go/ast`). Keep the check
IDs (M001…M013) consistent across ports so reviewers can point at
the same rule the same way in every language.

---

## Things to watch out for

- **A metric's identity is fixed once you use it.** If you need to
  change what it measures, rename it to `<name>.v2` and keep the
  old one running for 14 days with a `retired_at` date. Silent
  renames break every dashboard and alert rule that used the old
  name.
- **Never put raw exception messages in tag values.** Use
  `classify(exc)` to get one of ~9 `FailureClass` values. The
  `UNKNOWN` bucket is a feature, not a bug — if it starts rising,
  you've discovered a new kind of failure.
- **High-traffic duration metrics have to sample** (`sampling_rate
  < 1.0`). Metrics inside loops have to aggregate
  (`AggregatingCounter` / `DurationAccumulator`). Otherwise you
  flood Sentry.
- **Sentry Metrics API caveats.** The examples call
  `sentry_sdk.metrics.count/gauge/distribution`. The API has moved
  through beta — pin `sentry-sdk>=2.0` and double-check the call
  surface against your installed SDK. See
  `examples/python/README.md` for the tested version.
- **The reference examples need Python 3.11+** (uses `StrEnum` and
  the `X | Y` type syntax). TypeScript and Go ports are on the
  roadmap.

---

## Roadmap

- **v0.1** (you are here): Python reference. Seven agent adapters.
  MIT license. Used in production.
- **v0.2**: TypeScript/Node port (emission module, HTTP middleware,
  one external-API client, test gates).
- **v0.3**: Go port. Ready-made CI templates
  (`ci/github-actions.yml`, `ci/gitlab-ci.yml`, pre-commit hook).
- **Backlog**: Ruby, Java, Rust ports. An OpenTelemetry adapter (so
  the same `MetricDef` can also emit to OTel alongside Sentry).
  Auto-generated registry docs. A sibling `sentry-tracing` skill for
  spans.

---

## Contributing

- Open an issue with your language + framework + what's missing.
- PRs welcome for the adapter files (`adapters/<agent>.md`) and for
  porting `examples/python/` patterns to new languages.
- New `FailureClass` values need a short design discussion first —
  adding one affects every dashboard that filters on the taxonomy.
- Rewrites and clarifications to the reference docs are always
  welcome.

---

## License

MIT. Copyright © 2026 Torta Studios. See [LICENSE](LICENSE).

## Credits

Reverse-engineered from production observability at **Torta
Studios**. The skill ships the patterns — not the proprietary
business logic that sits on top of them.
