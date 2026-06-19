"""AI agent conversation tracing — the drop-in pattern for `gen_ai.*` spans.

This is the **tracing** companion to the metric helpers in
`emission_module.py`. It instruments an agent turn so it shows up in
Sentry's Explore -> Conversations view: one `gen_ai.invoke_agent` span
per run, with `gen_ai.chat` and `gen_ai.execute_tool` spans nested
under it, all stamped with a `gen_ai.conversation.id` so multi-turn
sessions group together.

Reference: references/ai-agent-conversations.md. Sentry docs:
  https://docs.sentry.io/ai/monitoring/conversations/
  https://docs.sentry.io/platforms/python/tracing/instrumentation/custom-instrumentation/ai-agents-module/

Drop in at `yourapp/observability/ai_spans.py` (or alongside
`observability.py`). Requires tracing to be enabled in `sentry_sdk.init`
(set `traces_sample_rate` or a `traces_sampler`) — conversations are
built from spans.

Two rules carried over from the metric helpers:

  1. *Observability never crashes the service.* `sentry_sdk.ai` is a
     beta API; `set_conversation_id` is capability-gated so a version
     bump can't raise in the request path.
  2. *Cardinality stays on the span, not the metric.* The conversation
     id and message bodies live on span attributes (unbounded is fine
     there). Never copy them into a `MetricDef` tag — see
     references/tagging-and-cardinality.md.

Python 3.11+ (PEP-604 unions). Pure-stdlib apart from `sentry-sdk>=2.0`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Iterator

import sentry_sdk

logger = logging.getLogger(__name__)


# ---- Conversation id (beta API, capability-gated) --------------------------


def set_conversation_id(conversation_id: str) -> None:
    """Stamp `gen_ai.conversation.id` onto subsequent gen_ai spans in scope.

    Wraps the beta `sentry_sdk.ai.set_conversation_id`. If the installed
    SDK predates the API (or it gets renamed), this degrades to a no-op
    instead of raising in the request path.
    """
    try:
        import sentry_sdk.ai
    except Exception:  # pragma: no cover - SDK without the beta module
        logger.debug("sentry_sdk.ai unavailable; conversation id not set")
        return

    set_id = getattr(sentry_sdk.ai, "set_conversation_id", None)
    if set_id is None:
        logger.debug("set_conversation_id unavailable; skipping")
        return

    try:
        set_id(conversation_id)
    except Exception:  # pragma: no cover - never crash the caller
        logger.exception("failed to set conversation id")


@contextmanager
def conversation_scope(conversation_id: str) -> Iterator[None]:
    """Isolate one turn so the conversation id can't bleed across requests.

        with conversation_scope(session.id):
            run_agent_turn(session, user_message)

    Derive `conversation_id` from your own session/thread identity (chat
    session uuid, DB row id) — NOT from the Sentry trace id. A single
    conversation can span multiple traces and vice versa.
    """
    with sentry_sdk.isolation_scope():
        set_conversation_id(conversation_id)
        yield


# ---- Message helpers -------------------------------------------------------
#
# Every `*.messages` span attribute is a STRINGIFIED JSON list of
# {role, parts} objects. Span attributes only hold primitives, so the
# list must be json.dumps'd and parseable.

Role = str  # "user" | "assistant" | "tool" | "system"


def text_message(role: Role, content: str) -> dict[str, Any]:
    """A user-visible `{role, parts:[{type:"text"}]}` message."""
    return {"role": role, "parts": [{"type": "text", "content": content}]}


def assistant_message(
    *, text: str, reasoning: str | None = None
) -> dict[str, Any]:
    """An assistant message; reasoning goes in a `reasoning` part, not `text`.

    The `reasoning` part keeps extended-thinking output out of the
    user-facing conversation view while still recording it for debugging.
    """
    parts: list[dict[str, Any]] = []
    if reasoning is not None:
        parts.append({"type": "reasoning", "content": reasoning})
    parts.append({"type": "text", "content": text})
    return {"role": "assistant", "parts": parts}


def dump_messages(messages: Sequence[Mapping[str, Any]]) -> str:
    """json.dumps a {role, parts} list for a `gen_ai.*.messages` attribute."""
    return json.dumps(list(messages))


# ---- Span context managers -------------------------------------------------


@contextmanager
def invoke_agent_span(
    agent_name: str, *, request_model: str | None = None
) -> Iterator[sentry_sdk.tracing.Span]:
    """Parent span for one agent run (`gen_ai.invoke_agent`).

        with invoke_agent_span("Weather Agent", request_model="o3-mini") as span:
            output = my_agent.run()
            span.set_data("gen_ai.output.messages",
                          dump_messages([assistant_message(text=str(output))]))
            span.set_data("gen_ai.usage.input_tokens", output.usage.input_tokens)
            span.set_data("gen_ai.usage.output_tokens", output.usage.output_tokens)
    """
    with sentry_sdk.start_span(
        op="gen_ai.invoke_agent", name=f"invoke_agent {agent_name}"
    ) as span:
        span.set_data("gen_ai.operation.name", "invoke_agent")
        span.set_data("gen_ai.agent.name", agent_name)
        if request_model is not None:
            span.set_data("gen_ai.request.model", request_model)
        yield span


@contextmanager
def chat_span(
    *,
    request_model: str,
    provider: str | None = None,
    input_messages: Sequence[Mapping[str, Any]] | None = None,
    agent_name: str | None = None,
    pipeline_name: str | None = None,
) -> Iterator[sentry_sdk.tracing.Span]:
    """One LLM call (`gen_ai.chat`).

    Set the response side after the call returns via `set_chat_response`.

        with chat_span(request_model="o3-mini", provider="openai",
                       input_messages=msgs) as span:
            result = client.chat.completions.create(model="o3-mini", messages=...)
            set_chat_response(span, result.model, output_messages=[...],
                              finish_reasons=[result.choices[0].finish_reason],
                              input_tokens=result.usage.prompt_tokens,
                              output_tokens=result.usage.completion_tokens)
    """
    with sentry_sdk.start_span(
        op="gen_ai.chat", name=f"chat {request_model}"
    ) as span:
        span.set_data("gen_ai.operation.name", "chat")
        span.set_data("gen_ai.request.model", request_model)
        if provider is not None:
            span.set_data("gen_ai.provider.name", provider)
        if agent_name is not None:
            span.set_data("gen_ai.agent.name", agent_name)
        if pipeline_name is not None:
            span.set_data("gen_ai.pipeline.name", pipeline_name)
        if input_messages is not None:
            span.set_data("gen_ai.input.messages", dump_messages(input_messages))
        yield span


def set_chat_response(
    span: sentry_sdk.tracing.Span,
    response_model: str,
    *,
    output_messages: Sequence[Mapping[str, Any]] | None = None,
    finish_reasons: Sequence[str] | None = None,
    input_tokens: int | None = None,
    input_tokens_cached: int | None = None,
    output_tokens: int | None = None,
    output_tokens_reasoning: int | None = None,
) -> None:
    """Record the response side of a `gen_ai.chat` span.

    Token totals INCLUDE their subsets: `input_tokens` already counts
    `input_tokens_cached`, and `output_tokens` already counts
    `output_tokens_reasoning`. Sentry computes cost as
    `(total - cached) * rate + cached * cached_rate`; passing the subsets
    as separate totals double-counts and can make cost go negative.
    """
    span.set_data("gen_ai.response.model", response_model)
    if output_messages is not None:
        span.set_data("gen_ai.output.messages", dump_messages(output_messages))
    if finish_reasons is not None:
        span.set_data(
            "gen_ai.response.finish_reasons", json.dumps(list(finish_reasons))
        )
    if input_tokens is not None:
        span.set_data("gen_ai.usage.input_tokens", input_tokens)
    if input_tokens_cached is not None:
        span.set_data("gen_ai.usage.input_tokens.cached", input_tokens_cached)
    if output_tokens is not None:
        span.set_data("gen_ai.usage.output_tokens", output_tokens)
    if output_tokens_reasoning is not None:
        span.set_data(
            "gen_ai.usage.output_tokens.reasoning", output_tokens_reasoning
        )


def execute_tool_span(
    tool_name: str, arguments: Any, run: Callable[[], Any]
) -> Any:
    """Run a tool inside a `gen_ai.execute_tool` span and record I/O.

        result = execute_tool_span(
            "get_weather", {"location": "Paris"},
            lambda: get_weather(location="Paris"),
        )

    `arguments` and the return value are json.dumps'd onto the span.
    """
    with sentry_sdk.start_span(
        op="gen_ai.execute_tool", name=f"execute_tool {tool_name}"
    ) as span:
        span.set_data("gen_ai.operation.name", "execute_tool")
        span.set_data("gen_ai.tool.name", tool_name)
        span.set_data("gen_ai.tool.call.arguments", json.dumps(arguments))
        result = run()
        span.set_data("gen_ai.tool.call.result", json.dumps(result))
        return result


# ---- End-to-end shape (illustrative) ---------------------------------------
#
#   with conversation_scope(session.id):
#       with invoke_agent_span("Weather Agent", request_model="o3-mini") as agent:
#           msgs = [text_message("user", user_input)]
#           with chat_span(request_model="o3-mini", provider="openai",
#                          input_messages=msgs, agent_name="Weather Agent") as c:
#               result = client.chat.completions.create(model="o3-mini", messages=...)
#               set_chat_response(
#                   c, result.model,
#                   output_messages=[assistant_message(text=result.choices[0].message.content)],
#                   finish_reasons=[result.choices[0].finish_reason],
#                   input_tokens=result.usage.prompt_tokens,
#                   output_tokens=result.usage.completion_tokens,
#               )
#           weather = execute_tool_span(
#               "get_weather", {"location": "Paris"},
#               lambda: get_weather(location="Paris"),
#           )
#           agent.set_data("gen_ai.output.messages",
#                          dump_messages([assistant_message(text=str(weather))]))
#
# Pair the failure path with a governed counter — the span shows one bad
# turn; emit_failure(AGENT_FAILURES, failure=classify(exc)) gives the rate
# SLI. See examples/python/workflow_decorator.py + failure_taxonomy.py.


__all__ = [
    "set_conversation_id",
    "conversation_scope",
    "text_message",
    "assistant_message",
    "dump_messages",
    "invoke_agent_span",
    "chat_span",
    "set_chat_response",
    "execute_tool_span",
]
