"""Instrumented retry loop — the drop-in pattern for bounded retries.

Drop-in at `yourapp/services/retry.py`. Emits one counter per loop
exit, tagged with `attempt_bucket` of the terminal attempt index +
outcome. Aggregates via `AggregatingCounter` internally so the
per-iteration path is zero emissions.

Usage:

    async for attempt in retry_with_instrumentation(
        metric=EXTERNAL_API_RETRY_OUTCOME,
        max_attempts=3,
        tags={"endpoint": "list"},
    ):
        async with attempt:
            return await client.fetch(...)

    # On success: emits one counter tagged outcome="success", attempt_bucket=<N>.
    # On final failure: outcome="failure", attempt_bucket=<N>. Exception re-raises.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Mapping
from typing import Any

from yourapp.observability import AggregatingCounter
from yourapp.shared.metric_tags import attempt_bucket
from yourapp.shared.metrics import MetricDef


class _Attempt:
    """One attempt in the loop. Entered with `async with attempt:`."""

    def __init__(
        self, idx: int, max_attempts: int, counter: AggregatingCounter
    ) -> None:
        self.idx = idx
        self.max_attempts = max_attempts
        self._counter = counter

    async def __aenter__(self) -> _Attempt:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any
    ) -> bool:
        if exc is None:
            # Successful attempt — terminate the loop.
            self._outcome = "success"
            return False
        if self.idx >= self.max_attempts:
            # Final attempt failed — propagate.
            self._outcome = "failure"
            return False
        # Swallow + retry.
        self._outcome = "retry"
        await asyncio.sleep(_backoff_seconds(self.idx))
        return True


async def retry_with_instrumentation(
    *,
    metric: MetricDef,
    max_attempts: int,
    tags: Mapping[str, str] | None = None,
) -> AsyncIterator[_Attempt]:
    """Yield `_Attempt` objects up to `max_attempts`.

    Emits one counter on loop exit, tagged with `attempt_bucket` of
    the terminal attempt index and `outcome ∈ {"success", "failure"}`.
    """

    final_idx = 0
    final_outcome = "failure"
    base_tags = dict(tags or {})

    try:
        for idx in range(1, max_attempts + 1):
            final_idx = idx
            # The counter aggregates loop-internal emissions (none in
            # this pattern, but the context is what the CI gate keys
            # off to permit the metric to appear inside the yield).
            with AggregatingCounter(metric, tags={**base_tags}) as counter:
                attempt = _Attempt(idx, max_attempts, counter)
                yield attempt
                if getattr(attempt, "_outcome", None) == "success":
                    final_outcome = "success"
                    return
                if getattr(attempt, "_outcome", None) == "failure":
                    return
    finally:
        # Single emission summarizing the loop outcome.
        from yourapp.observability import emit_counter

        emit_counter(
            metric,
            tags={
                **base_tags,
                "attempt_bucket": attempt_bucket(final_idx),
                "outcome": final_outcome,
            },
        )


def _backoff_seconds(attempt_idx: int) -> float:
    """Exponential backoff: 0.25s, 0.5s, 1s, 2s, …"""

    return 0.25 * (2 ** (attempt_idx - 1))


# Example metric definition for the retry surface:
#
#     EXTERNAL_API_RETRY_OUTCOME = MetricDef.counter(
#         "external_api.retry.outcome.count",
#         purpose="outcome",
#         owner="platform",
#         means=(
#             "Outcome of a retrying call wrapped by retry_with_instrumentation. "
#             "attempt_bucket tags the final attempt index; outcome tags the "
#             "terminal state."
#         ),
#         tags={
#             "endpoint": frozenset({"list", "detail", "search"}),
#             "attempt_bucket": "attempt_bucket",
#             "outcome": frozenset({"success", "failure"}),
#         },
#         emit_frequency="per_event",
#         loop_policy="aggregate_only",
#     )


__all__ = ["retry_with_instrumentation"]
