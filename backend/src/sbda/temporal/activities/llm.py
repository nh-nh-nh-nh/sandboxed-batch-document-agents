"""`call_claude` activity. See SPEC.md §9.1.

Converts Anthropic SDK response objects to plain JSON-serializable dataclasses
at the activity boundary (§7.3) — no SDK objects survive into workflow state.

Retry semantics (most-specific-first, per the §9.1 table):
  - `RateLimitError` (429): retryable, budgeted separately from other
    retryable errors — up to `MAX_RATE_LIMIT_ATTEMPTS` (50) attempts. The
    `retry-after` header drives `next_retry_delay` directly (Temporal's own
    backoff is bypassed for this error type), capped at
    `_MAX_RATE_LIMIT_RETRY_DELAY_S` so a large header value can't hold the
    workflow (and its already-provisioned sandbox) past its own run timeout.
    The attempt count is tracked via `activity.heartbeat()` and restored from
    `activity.info().heartbeat_details` on each retry, since a fresh activity
    invocation has no in-memory state of its own.
  - `APIStatusError` 5xx / `APIConnectionError` (timeout, network): retryable,
    budgeted separately — up to `MAX_OTHER_RETRYABLE_ATTEMPTS` (3) attempts,
    also heartbeat-persisted. Delay follows the `call_claude` `RetryPolicy`'s
    own exponential backoff (see `temporal/shared.py`).
  - Once either budget is exhausted, the activity raises a non-retryable
    `ApplicationError` itself rather than relying on the outer `RetryPolicy`
    (which only serves as a high safety-net ceiling — see `shared.py`).
  - `BadRequestError`, `AuthenticationError`, `PermissionDeniedError` (4xx):
    wrapped as `LLMClientError`, which is in `non_retryable_error_types` for
    the `call_claude` retry policy (see `temporal/shared.py`) — Temporal will
    not retry it, and the child workflow fails with `error_category=LLM`.

The Anthropic SDK's own `max_retries` is disabled (set to 0) so it can't
retry underneath Temporal and desynchronize these counters from what actually
happened.

Accepted tradeoff (§9.1, §16.3): LLM calls are not idempotent and there is no
response cache. If this activity times out *after* Anthropic has already
completed the call, Temporal's retry re-bills it. Bounded by
`max_concurrent_activities` and the per-error-type attempt budgets on this
activity, but real — the fix later is an `llm_call_cache` table keyed on
`(workflow_id, turn_index)`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

import anthropic
from temporalio import activity
from temporalio.exceptions import ApplicationError

from sbda.agent.messages import build_request
from sbda.config import settings
from sbda.core.errors import LLMClientError

MAX_RATE_LIMIT_ATTEMPTS = 50
MAX_OTHER_RETRYABLE_ATTEMPTS = 3
# Caps the Temporal-scheduled `next_retry_delay` derived from `retry-after`
# well under FILE_WORKFLOW_SINGLE_ATTEMPT_RUN_TIMEOUT/FILE_WORKFLOW_RUN_TIMEOUT
# (temporal/shared.py) — `next_retry_delay` bypasses the RetryPolicy's own
# `maximum_interval` clamp, so a large `retry-after` would otherwise be able
# to hold the whole workflow (and its already-provisioned sandbox) past its
# run timeout, which is a hard stop that skips `finally` cleanup.
_MAX_RATE_LIMIT_RETRY_DELAY_S = 60.0


@dataclass
class LLMInput:
    messages: list[dict]
    force_report: bool = False


@dataclass
class LLMResult:
    content: list[dict]
    stop_reason: str | None
    usage: dict = field(default_factory=dict)


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=0)


def _content_block_to_dict(block) -> dict:
    if isinstance(block, dict):
        return block
    # Anthropic SDK content blocks are pydantic models.
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return dict(block)


def _response_to_result(message) -> LLMResult:
    content = [_content_block_to_dict(b) for b in message.content]
    usage = message.usage
    usage_dict = (
        usage.model_dump() if hasattr(usage, "model_dump") else dict(usage or {})
    )
    return LLMResult(
        content=content,
        stop_reason=message.stop_reason,
        usage=usage_dict,
    )


@dataclass(frozen=True)
class _RetryCounts:
    rate_limit: int
    other_retryable: int


def _restore_retry_counts() -> _RetryCounts:
    """Restore per-error-type attempt counts persisted via `activity.heartbeat()`
    on a prior attempt. A fresh activity invocation has no in-memory state of
    its own, so this is the only way to know how much of each budget has
    already been spent. `call_claude` is the only writer of this heartbeat
    state, so a malformed `state` here means the format itself is broken —
    that should surface as a loud activity failure, not be silently swallowed
    into a fresh budget.
    """
    if not activity.in_activity():
        return _RetryCounts(0, 0)
    info = activity.info()
    if info.attempt <= 1 or not info.heartbeat_details:
        return _RetryCounts(0, 0)
    state = info.heartbeat_details[0]
    return _RetryCounts(
        int(state.get("rate_limit_attempts", 0)),
        int(state.get("other_retryable_attempts", 0)),
    )


def _heartbeat_retry_counts(counts: _RetryCounts) -> None:
    if activity.in_activity():
        activity.heartbeat(
            {
                "rate_limit_attempts": counts.rate_limit,
                "other_retryable_attempts": counts.other_retryable,
            }
        )


def _raise_budgeted(
    exc: Exception,
    error_type: str,
    attempts: int,
    max_attempts: int,
    counts: _RetryCounts,
    next_retry_delay: timedelta | None = None,
):
    """Raise the appropriate `ApplicationError` for a retryable LLM error:
    non-retryable once `attempts` exceeds `max_attempts` (budget exhausted),
    otherwise heartbeat the updated `counts` and raise retryable.
    """
    if attempts > max_attempts:
        raise ApplicationError(str(exc), type=error_type, non_retryable=True) from exc
    _heartbeat_retry_counts(counts)
    raise ApplicationError(
        str(exc), type=error_type, non_retryable=False, next_retry_delay=next_retry_delay
    ) from exc


@activity.defn
async def call_claude(input: LLMInput) -> LLMResult:
    client = _get_client()
    request = build_request(input.messages, force_report=input.force_report)
    counts = _restore_retry_counts()

    try:
        message = await asyncio.to_thread(client.messages.create, **request)
    except anthropic.RateLimitError as e:
        rate_limit_attempts = counts.rate_limit + 1
        retry_after = _extract_retry_after(e)
        next_retry_delay = (
            timedelta(seconds=min(retry_after, _MAX_RATE_LIMIT_RETRY_DELAY_S))
            if retry_after is not None and retry_after >= 0
            else None
        )
        _raise_budgeted(
            e,
            "RateLimitError",
            rate_limit_attempts,
            MAX_RATE_LIMIT_ATTEMPTS,
            _RetryCounts(rate_limit_attempts, counts.other_retryable),
            next_retry_delay,
        )
    except (
        anthropic.BadRequestError,
        anthropic.AuthenticationError,
        anthropic.PermissionDeniedError,
    ) as e:
        raise LLMClientError(str(e)) from e
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        other_retryable_attempts = counts.other_retryable + 1
        _raise_budgeted(
            e,
            type(e).__name__,
            other_retryable_attempts,
            MAX_OTHER_RETRYABLE_ATTEMPTS,
            _RetryCounts(counts.rate_limit, other_retryable_attempts),
        )

    return _response_to_result(message)


def _extract_retry_after(exc: anthropic.RateLimitError) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if not headers:
        return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
