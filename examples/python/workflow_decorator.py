"""Workflow-step decorator — the drop-in pattern for workflow-engine tasks
(Hatchet, Celery, Temporal, Sidekiq, Inngest, BullMQ, or any
equivalent).

Drop-in at `yourapp/services/<workflow>/instrumentation.py`. The
decorator wraps a task function with the step-boundary triad:
duration (always) + failure counter (on exception, tagged by
`FailureClass.classify(exc)`).

Usage (workflow engine of your choice):

    @workflow.task(retries=2, execution_timeout="5m")
    @instrumented_step(stages.INGEST)     # replace with your domain stage
    async def ingest(input, ctx):
        ...

Decorator order matters: `@instrumented_step(...)` sits INSIDE
`@workflow.task(...)` so the engine's registration sees the wrapped
function (`functools.wraps` preserves signature for the engine's
input validator).

The exception is emitted-on and re-raised — the decorator is
observational, not swallowing.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

from yourapp.observability import emit_failure, emit_latency
from yourapp.shared.failure_taxonomy import classify
from yourapp.shared.metrics import MetricDef

P = ParamSpec("P")
R = TypeVar("R")
AsyncFn = Callable[P, Coroutine[Any, Any, R]]

logger = logging.getLogger(__name__)


# ---- Metric definitions ----------------------------------------------------

WORKFLOW_STEP_DURATION = MetricDef.latency(
    "workflow.step.duration",
    owner="platform",
    means="Wall-clock duration of a workflow step, measured around the task body.",
    tags={"stage": "stage_name"},   # enumerated per-project — use a literal frozenset in practice
    emit_frequency="per_step",
)

WORKFLOW_STEP_FAILURES = MetricDef.failure_counter(
    "workflow.step.failure.count",
    owner="platform",
    means="A workflow step raised after its retry budget; tagged by FailureClass.classify(exc).",
    tags={"stage": "stage_name"},
    emit_frequency="per_step",
)


# ---- Decorator -------------------------------------------------------------


def instrumented_step(stage_name: str) -> Callable[[AsyncFn[P, R]], AsyncFn[P, R]]:
    """Return a decorator that records duration + failure count for a stage."""

    tags = {"stage": stage_name}

    def decorator(fn: AsyncFn[P, R]) -> AsyncFn[P, R]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            logger.info("step starting: %s", stage_name)
            started = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                emit_latency(WORKFLOW_STEP_DURATION, duration_ms=elapsed_ms, tags=tags)
                emit_failure(WORKFLOW_STEP_FAILURES, failure=classify(exc), tags=tags)
                logger.exception(
                    "step failed: %s (%s)", stage_name, type(exc).__name__
                )
                raise
            elapsed_ms = (time.monotonic() - started) * 1000.0
            emit_latency(WORKFLOW_STEP_DURATION, duration_ms=elapsed_ms, tags=tags)
            logger.info("step completed: %s (%.0fms)", stage_name, elapsed_ms)
            return result

        return wrapper

    return decorator


__all__ = [
    "WORKFLOW_STEP_DURATION",
    "WORKFLOW_STEP_FAILURES",
    "instrumented_step",
]
