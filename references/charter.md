# Charter

This skill governs **system-behavior instrumentation** via Sentry. It
defines what signals the service is allowed to emit, how they are
named and shaped, where they are emitted from, how much they may cost,
and how misuse is prevented by default.

The skill started as Metrics governance and is **evolving to cover
tracing** where Sentry ships a product that depends on specific span
conventions. The first tracing surface is AI agent conversations
(`gen_ai.*` spans); more tracing conventions can join under the same
governance principles (closed sets for group-by tags, free-form text
on spans not metrics, observability never crashes the service).

## What's in scope

- Sentry Application Metrics (counter / gauge / distribution).
- Duration measurement around external calls, workflow steps, and
  request lifecycles.
- Failure counters bucketed through a bounded taxonomy.
- Resource accounting (tokens, quota units, bytes).
- Correctness counters for assumption-violation events (parse
  failures, taxonomy fallbacks).
- **AI agent conversation tracing**: `gen_ai.*` spans
  (`invoke_agent` / `chat` / `execute_tool`), `gen_ai.conversation.id`,
  and per-call token/message attributes for Sentry's Conversations
  view (Explore → Agents). See `ai-agent-conversations.md`.

## What's out of scope

- **Product analytics**: button clicks, funnel progression, feature-
  flag exposure. These belong in your product-analytics tool (PostHog,
  Amplitude, Mixpanel, etc.), not in Sentry instrumentation.
- **Dashboards, alert rules, SLO thresholds, on-call policy**: these
  are downstream consumers of the metrics this skill defines. Clean
  instrumentation is a precondition; the dashboards themselves are
  decided outside the code.
- **General distributed tracing conventions** (span naming, span
  attributes, span kinds for arbitrary services): still out of scope —
  large enough for its own skill. The one tracing surface this skill
  *does* cover is the `gen_ai.*` namespace (above), because Sentry's
  Conversations product reads those exact attributes.
- **Logs**: routed through the project's logger (typically via Sentry's
  `LoggingIntegration`). Metric decisions don't dictate log content.

## Principles

1. **Closed sets for what you group by; declared ids for what you
   look up.** Every group-by tag value is either enumerated verbatim
   in `MetricDef.tag_constraints` or is the output of an approved
   bucket function, because alert rules and dashboards need stable
   values. High-cardinality ids (account, project, order, replay) are
   allowed as declared `context=` attributes — Sentry stores full
   metric events, so they are queryable. Raw exception strings,
   free-form text, emails, raw URLs and timestamps are forbidden on a
   metric in either role. See `tagging-and-cardinality.md`.
2. **Identity is immutable.** A metric's
   `(name, kind, unit, purpose, allowed_tags, tag_constraints)` tuple
   cannot change under the same name. Meaning change = new versioned
   name.
3. **The correct path is the easiest path.** If emitting correctly
   requires memorizing 11 fields, people will cargo-cult or bypass.
   Constructors fill in the cross-cutting fields; surface patterns
   bake in the emissions. Hand-rolling is always more code than using
   the helper.
4. **Observability never crashes the service.** Emission helpers catch
   every exception from the SDK and drop the emission silently in
   production. In pytest + non-production environments, validator
   failures raise so misuse is caught in CI.
5. **Unknown is a signal.** The `UNKNOWN` failure bucket's rate is its
   own SLI. A rising `UNKNOWN` rate means a new exception class is
   being raised without a registration, or a dependency is failing in
   a shape nobody modeled. Either way it's actionable.
6. **Cost is a first-class attribute.** Sentry bills metrics by data
   volume, and Spike Protection doesn't cover them. Hot-path
   distributions sample; loops aggregate; rate limits drop beyond a
   cap. Every `MetricDef` declares its cost shape so the helper + CI
   gate can enforce it uniformly. See `cost-model.md`.

## How this skill earns its keep

Without governed instrumentation you get:

- Raw `str(exc)` leaking into tag values (PII risk, alert rules
  can't match, group-bys return one row per message).
- Emissions in tight loops (billed volume multiplies by the loop
  length).
- Silently renamed metrics (dashboards go dark overnight; no audit
  trail).
- New metrics invented per feature that duplicate existing coverage
  under different names.
- Failure counters tagged `exception="AttributeError: 'NoneType' object..."`
  that an SRE can't group across services.

Each failure mode has a rule in the charter that prevents it *by
construction* — using the helpers correctly is less work than breaking
them.
