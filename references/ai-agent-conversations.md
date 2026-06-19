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
[AI monitoring / Conversations](https://docs.sentry.io/ai/monitoring/conversations/)
and
[Python custom instrumentation / AI Agents module](https://docs.sentry.io/platforms/python/tracing/instrumentation/custom-instrumentation/ai-agents-module/).

Python drop-in: `examples/python/ai_agent_spans.py`.

---

## What a conversation is

A **conversation** is a collection of spans that share the same
`gen_ai.conversation.id` attribute. It usually maps to one chat session
with your AI assistant. Sentry's **Explore → Conversations** view groups
traces by this id and reconstructs the full message history (user
inputs, assistant responses, tool calls) plus estimated cost, token
usage, LLM-call count, and tool-call count.

Two prerequisites, both required:

1. **Tracing enabled** with the Sentry SDK initialised for the project
   (`traces_sample_rate` set, or a `traces_sampler`). Conversations are
   built from spans — no tracing, no conversations.
2. **`gen_ai.conversation.id` set** on the AI spans you want grouped.

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
**not** from the Sentry trace id.

---

## Setting the conversation id (Python)

> **Stability: beta.** `sentry_sdk.ai` is beta; the import path and
> behaviour may change. Pin your `sentry-sdk` version and gate the call
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
| `gen_ai.usage.input_tokens.cached` | – | cached **subset** of the above |
| `gen_ai.usage.output_tokens` | – | total output tokens (incl. reasoning) |
| `gen_ai.usage.output_tokens.reasoning` | – | reasoning **subset** of the above |

Optional context: `gen_ai.agent.name` (parent agent),
`gen_ai.pipeline.name` (workflow / pipeline id).

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
`"chat o3-mini"`, `"execute_tool get_weather"`.

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
- `gen_ai.usage.input_tokens.cached = 90` — the cached portion of that 100.
- `gen_ai.usage.output_tokens` — total output, **including** reasoning.
- `gen_ai.usage.output_tokens.reasoning` — the reasoning portion.

Sentry computes cost as
`(total − cached) × standard_rate + cached × cached_rate`. If you
report cached/reasoning as separate totals (double-counting), the
subtraction can go negative and the cost is wrong.

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
  wrapper. Don't tag those metrics with the conversation id — it's
  unbounded cardinality (see `tagging-and-cardinality.md`); the id
  belongs on the span only.
- **Latency:** the span duration is the per-call latency; a
  `MetricDef.latency` around the agent turn gives you the percentile
  rollup.

Rule of thumb: **span attributes carry high-cardinality per-call
context (conversation id, message bodies); metric tags stay in closed,
bounded sets.** Never copy `gen_ai.conversation.id` into a metric tag.

---

## Checklist

- [ ] Tracing enabled (`traces_sample_rate` / `traces_sampler` set).
- [ ] `gen_ai.conversation.id` set once per turn, from your own session
      identity, inside an isolation scope.
- [ ] `set_conversation_id` call is capability-gated so a beta API change
      can't crash the request path.
- [ ] `invoke_agent` span wraps the run; `chat` / `execute_tool` nest under it.
- [ ] Required attrs present per span type (operation name always;
      models for chat; agent name for invoke; tool name for execute).
- [ ] `*.messages` are `json.dumps`'d `{role, parts}` lists.
- [ ] Reasoning output uses a `reasoning` part, not `text`.
- [ ] Token totals include their cached/reasoning subsets — not double-counted.
- [ ] Agent/tool failures also emit a governed `failure_counter`.
- [ ] No conversation id (or any unbounded value) on a metric tag.
