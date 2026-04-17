# Charter

This skill governs **system-behavior instrumentation** via Sentry. It
defines what signals the service is allowed to emit, how they are
named and shaped, where they are emitted from, how much they may cost,
and how misuse is prevented by default.

## What's in scope

- Sentry Metrics (counter / gauge / distribution).
- Duration measurement around external calls, workflow steps, and
  request lifecycles.
- Failure counters bucketed through a bounded taxonomy.
- Resource accounting (tokens, quota units, bytes).
- Correctness counters for assumption-violation events (parse
  failures, taxonomy fallbacks).

## What's out of scope

- **Product analytics** (PostHog events): button clicks, funnel
  progression, feature-flag exposure. Use the sibling
  `posthog-analytics` skill.
- **Dashboards, alert rules, SLO thresholds, on-call policy**: these
  are downstream consumers of the metrics this skill defines. Clean
  instrumentation is a precondition; the dashboards themselves are
  decided outside the code.
- **Distributed tracing conventions** (span naming, span attributes,
  span kinds): related but large enough for its own skill.
- **Logs**: routed through the project's logger (typically via Sentry's
  `LoggingIntegration`). Metric decisions don't dictate log content.

## Principles

1. **Closed sets over open strings.** Every tag value is either
   enumerated verbatim in `MetricDef.tag_constraints` or is the output
   of an approved bucket function. Raw exception strings, user ids,
   URLs, timestamps — all forbidden as tag values.
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
6. **Cost is a first-class attribute.** Hot-path distributions sample;
   loops aggregate; rate limits drop beyond a cap. Every `MetricDef`
   declares its cost shape so the helper + CI gate can enforce it
   uniformly.

## How this skill earns its keep

Without governed instrumentation you get:

- Raw `str(exc)` leaking into tag values (PII risk, cardinality
  blowup, alert rules can't match).
- Distributions in tight loops (Sentry bill explodes; percentiles
  distort).
- Silently renamed metrics (dashboards go dark overnight; no audit
  trail).
- New metrics invented per feature that duplicate existing coverage
  under different names.
- Failure counters tagged `exception="AttributeError: 'NoneType' object..."`
  that an SRE can't group across services.

Each failure mode has a rule in the charter that prevents it *by
construction* — using the helpers correctly is less work than breaking
them.
