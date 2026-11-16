# AI agent conversations (gen_ai spans)

> **First tracing surface in the skill.** The skill started as Sentry
> **Metrics** governance (counter / gauge / distribution) and is growing
> to cover **tracing** as well. This reference is the first instalment:
> the `gen_ai.*` span conventions Sentry's AI Agents / Conversations
> product reads. Metrics and tracing are complementary — emit `gen_ai`
> spans for per-call trace detail, *and* keep emitting governed
> `MetricDef` counters/latencies for the SLO-grade rollups. Token usage
> is already in this skill's charter as resource accounting; conversation
> tracing is where those tokens get their per-turn context.

Reference: Sentry docs —
[Conversations](https://docs.sentry.io/product/agents/conversations/),
[Python agent tracing — manual instrumentation](https://docs.sentry.io/platforms/python/agent-tracing/manual-instrumentation/),
and the SDK-side
[AI Agents module spec](https://develop.sentry.dev/sdk/telemetry/traces/modules/ai-agents/).
Checked against these pages on 2026-11-16; the earlier
`/ai/monitoring/conversations/` and `/product/explore/conversations/`
URLs no longer resolve to a Conversations page.

Python drop-in: `examples/python/ai_agent_spans.py`.

---

## What a conversation is

A **conversation** is a collection of spans that share the same
`gen_ai.conversation.id` attribute. It usually maps to one chat session
with your AI assistant. Sentry's **Conversations** view (the
Conversations tab under **Explore → Agents**) groups
spans by this id and reconstructs the full message history (user
inputs, assistant responses, tool calls) plus estimated cost, token
usage, LLM-call count, and tool-call count.

Two prerequisites, both required:

1. **Tracing enabled** with the Sentry SDK initialised for the project
   (`traces_sample_rate` set, or a `traces_sampler`). Conversations are
   built from spans — no tracing, no conversations.
2. **`gen_ai.conversation.id` set** on the AI spans you want grouped.

SDK version: Sentry's Python docs say that from `sentry-sdk` 2.64.0
gen_ai spans are sent in the standalone format Conversations requires.
Use 2.64.0 or later. For a conversation to get a title, its spans need
`gen_ai.input.messages` containing a `user` message.

### Conversations and traces are independent

Do not assume one trace == one conversation:

- **One conversation can span multiple traces.** A user refreshes the
  page mid-chat; the second half lands in a new trace but the same
  conversation id stitches them together.
- **One trace can hold multiple conversations.** A long-lived process
  starts a new chat session without a page refresh; two conversation
  ids appear under one trace.

The id is what groups; the trace boundary is incidental. Derive the id
from your own session/thread identity (DB row id, chat-session uuid),
**not** from the Sentry trace or request id — Sentry's docs say to omit
the id rather than derive one. Use a short opaque identifier
(alphanumerics, dashes, underscores); not a URL, an email address, or
free text.

---

## Setting the conversation id (Python)

> **Stability.** Sentry's docs don't label `sentry_sdk.ai` or
> Conversations as beta or GA, and don't give a minimum version for
> `set_conversation_id`. Pin your `sentry-sdk` version and gate the call
> with a capability check (see the example module) so a version bump
> can't crash the request path — same "observability never crashes the
> service" rule the metric helpers follow.

```python
import sentry_sdk.ai

# Stamp every subsequent gen_ai span in the current scope with this id.
sentry_sdk.ai.set_conversation_id("conv_abc123")
```

`set_conversation_id` writes `gen_ai.conversation.id` onto AI spans in
the **current scope**. Set it once, at the top of the request / turn
handler, before any agent or LLM span opens. To stop tagging (e.g. when
a worker thread is reused across sessions) call `remove_conversation_id()`
on the scope.

Isolate per request so ids don't bleed across concurrent turns:

```python
with sentry_sdk.isolation_scope():
    sentry_sdk.ai.set_conversation_id(session.id)
    await run_agent_turn(session, user_message)
```

### Auto-set by some integrations

A few integrations infer the id for you — don't double-set it:

- **OpenAI Agents SDK (Python)** and **OpenAI SDK (Node)** infer it
  automatically.
- The **OpenAI** integration sets it when you pass the Conversations
  API:

  ```python
  conversation = openai.conversations.create()
  response = openai.responses.create(
      model="gpt-4.1",
      input=[{"role": "user", "content": "..."}],
      conversation=conversation.id,   # → gen_ai.conversation.id
  )
  ```

If you use one of these, skip the manual `set_conversation_id` for those
calls; set it manually only on spans the integration doesn't own.

---

## Span types and required attributes

Three operations cover an agent turn. Each is a normal
`sentry_sdk.start_span` with a `gen_ai.*` `op` and a set of
`gen_ai.*` data attributes.

### `gen_ai.invoke_agent` — one agent run

| Attribute | Required | Value |
|---|---|---|
| `gen_ai.operation.name` | ✓ | `"invoke_agent"` |
| `gen_ai.agent.name` | ✓ | the agent's name |
| `gen_ai.request.model` | – | model the agent drives |
| `gen_ai.output.messages` | – | final assistant output (`{role, parts}` JSON) |
| `gen_ai.usage.input_tokens` / `.output_tokens` | – | totals for the run |

### `gen_ai.chat` — one LLM call

| Attribute | Required | Value |
|---|---|---|
| `gen_ai.operation.name` | ✓ | `"chat"` |
| `gen_ai.request.model` | ✓ | requested model id |
| `gen_ai.response.model` | ✓ | model that actually answered |
| `gen_ai.provider.name` | – | `"openai"`, `"anthropic"`, … |
| `gen_ai.input.messages` | – | prompt (`{role, parts}` JSON) |
| `gen_ai.output.messages` | – | completion (`{role, parts}` JSON) |
| `gen_ai.response.finish_reasons` | – | JSON list of finish reasons |
| `gen_ai.usage.input_tokens` | – | **total** input tokens (incl. cached) |
| `gen_ai.usage.cache_read.input_tokens` | – | cache-read **subset** of the above |
| `gen_ai.usage.cache_creation.input_tokens` | – | cache-write **subset** of the above |
| `gen_ai.usage.output_tokens` | – | total output tokens (incl. reasoning) |
| `gen_ai.usage.reasoning.output_tokens` | – | reasoning **subset** of the above |
| `gen_ai.system_instructions` | – | the system prompt (keep it out of `input.messages`) |

Optional context: `gen_ai.agent.name` (parent agent),
`gen_ai.pipeline.name` (workflow / pipeline id).

**Renamed attributes.** Sentry's Python docs mark these as deprecated;
use the replacement:

| Deprecated | Use instead |
|---|---|
| `gen_ai.usage.input_tokens.cached` | `gen_ai.usage.cache_read.input_tokens` |
| `gen_ai.usage.input_tokens.cache_write` | `gen_ai.usage.cache_creation.input_tokens` |
| `gen_ai.usage.output_tokens.reasoning` | `gen_ai.usage.reasoning.output_tokens` |
| `gen_ai.request.messages` | `gen_ai.input.messages` |
| `gen_ai.request.available_tools` | `gen_ai.tool.definitions` |
| `gen_ai.response.text`, `gen_ai.response.tool_calls` | `gen_ai.output.messages` |
| `gen_ai.tool.input` / `gen_ai.tool.output` | `gen_ai.tool.call.arguments` / `gen_ai.tool.call.result` |

Don't set `gen_ai.cost.*`, `gen_ai.usage.total_tokens` or
`gen_ai.response.tokens_per_second` yourself — Sentry derives them at
ingestion.

### `gen_ai.execute_tool` — one tool call

| Attribute | Required | Value |
|---|---|---|
| `gen_ai.operation.name` | ✓ | `"execute_tool"` |
| `gen_ai.tool.name` | ✓ | tool / function name |
| `gen_ai.tool.call.arguments` | – | stringified-JSON input |
| `gen_ai.tool.call.result` | – | stringified-JSON output |

### Span hierarchy

`invoke_agent` is the parent; `chat` and `execute_tool` nest under it:

```
invoke_agent My Agent          (gen_ai.invoke_agent)
├── chat gpt-4o                 (gen_ai.chat)
├── execute_tool get_weather    (gen_ai.execute_tool)
├── chat gpt-4o                 (gen_ai.chat)
└── …
```

Name spans `"<operation> <subject>"` — `"invoke_agent Weather Agent"`,
`"chat o3-mini"`, `"execute_tool get_weather"`. The span `op` must be
`"gen_ai.<operation name>"`.

Set the request-side attributes when the span starts, before the model
or tool call, so head-based sampling can use them. On failure, set the
span status to error and record `error.type`.

Sentry documents further operations this skill doesn't wrap yet:
`embeddings`, `decide`, `extract` and memory operations. Follow the
manual-instrumentation page for those.

### Span API note

The examples use the sentry-sdk 2.x API (`start_span(op=..., name=...)`
and `span.set_data(...)`). In span-streaming mode
(`trace_lifecycle="stream"`, the only mode in SDK 3.x) attributes are
set with `set_attribute` / `attributes={...}` instead.

### Privacy

The automatic integrations gate prompt and response capture behind SDK
options (`send_default_pii` / `include_prompts` before SDK 3.0;
`data_collection={"gen_ai": {...}}` after). **Attributes you set by hand
are not filtered by those options.** If prompt text must not leave your
system, don't put it on the span.

---

## Message format — `{role, parts}`

Every `*.messages` attribute is a **stringified JSON list** of
`{role, parts}` objects. Span attributes only hold primitives, so you
**must** `json.dumps(...)` the list; it must be parseable JSON.

```json
[
  {"role": "user", "parts": [{"type": "text", "content": "Tell me a joke"}]}
]
```

- **Roles:** `"user"`, `"assistant"`, `"tool"`, `"system"`.
- **Part types:** `"text"` (user-visible), `"reasoning"` (model
  thinking), `"tool_call"`, `"tool_call_response"`.

### Reasoning / thinking content

Put extended-thinking output in a `{"type": "reasoning", ...}` part, not
a `text` part. This keeps it out of the user-facing conversation view
while still recording it for debugging:

```python
span.set_data("gen_ai.output.messages", json.dumps([
    {"role": "assistant", "parts": [
        {"type": "reasoning", "content": "6 times 7 is 42."},
        {"type": "text", "content": "The answer is 42."},
    ]}
]))
```

---

## Token accounting — subsets, not separate counts

Cached and reasoning tokens are **subsets** of the totals, not
additional buckets:

- `gen_ai.usage.input_tokens = 100` — total input, **including** cached.
- `gen_ai.usage.cache_read.input_tokens = 90` — the cached portion of that 100.
- `gen_ai.usage.output_tokens` — total output, **including** reasoning.
- `gen_ai.usage.reasoning.output_tokens` — the reasoning portion.

Sentry derives cost from these at ingestion. Its SDK spec warns that
reporting only the non-cached tokens as `input_tokens` "produces
negative costs". Report the full totals and let the subset attributes
say how much of each was cached or reasoning.

---

## How this composes with the metric governance

`gen_ai` spans give per-call trace detail; they are **not** a substitute
for the governed metrics this skill defines:

- **Failures:** wrap the agent/tool body and emit a
  `MetricDef.failure_counter` tagged via `classify(exc)` (see
  `failure-taxonomy.md`) *in addition to* recording the exception on the
  span. The span shows one bad turn; the counter gives you the rate SLI.
- **Token resource accounting:** the `gen_ai.usage.*` span attributes are
  per-call; if you also want an aggregate token gauge/counter for
  budgeting, register a `MetricDef.resource(...)` and emit from the same
  wrapper. The conversation id is never a group-by `tags=` value on
  those metrics. If you want to get from a token spike to the
  conversation, declare `conversation_id` as `context=` (see
  `tagging-and-cardinality.md`).
- **Latency:** the span duration is the per-call latency; a
  `MetricDef.latency` around the agent turn gives you the percentile
  rollup.

Rule of thumb: **message bodies and tool payloads live on spans only;
metric group-by tags stay in closed, bounded sets; ids a metric needs
for lookup are declared `context=`.**

---

## Checklist

- [ ] Tracing enabled (`traces_sample_rate` / `traces_sampler` set).
- [ ] `gen_ai.conversation.id` set once per turn, from your own session
      identity, inside an isolation scope.
- [ ] `set_conversation_id` call is capability-gated so an SDK change
      can't crash the request path.
- [ ] `sentry-sdk` is 2.64.0 or later.
- [ ] `invoke_agent` span wraps the run; `chat` / `execute_tool` nest under it.
- [ ] Required attrs present per span type (operation name always;
      models for chat; agent name for invoke; tool name for execute).
- [ ] `*.messages` are `json.dumps`'d `{role, parts}` lists.
- [ ] Reasoning output uses a `reasoning` part, not `text`.
- [ ] Token totals include their cached/reasoning subsets — not double-counted.
- [ ] Agent/tool failures also emit a governed `failure_counter`.
- [ ] No conversation id in a metric's `tags=`; no message text on any
      metric.
- [ ] No deprecated `gen_ai.*` attribute names.
