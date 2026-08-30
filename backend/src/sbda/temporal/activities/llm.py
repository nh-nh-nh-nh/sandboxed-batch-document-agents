"""`call_claude` activity. See SPEC.md §9.1.

Converts Anthropic SDK response objects to plain JSON-serializable dataclasses
at the activity boundary (§7.3) — no SDK objects survive into workflow state.

Retry semantics (most-specific-first, per the §9.1 table):
  - `RateLimitError` (429): retryable; honor `retry-after` by sleeping
    in-activity up to 60s, then let Temporal back off further.
  - `APIStatusError` 5xx: retryable.
  - `APIConnectionError` / timeout: retryable.
  - `BadRequestError`, `AuthenticationError`, `PermissionDeniedError` (4xx):
    wrapped as `LLMClientError`, which is in `non_retryable_error_types` for
    the `call_claude` retry policy (see `temporal/shared.py`) — Temporal will
    not retry it, and the child workflow fails with `error_category=LLM`.

Accepted tradeoff (§9.1, §16.3): LLM calls are not idempotent and there is no
response cache. If this activity times out *after* Anthropic has already
completed the call, Temporal's retry re-bills it. Bounded by
`max_concurrent_activities` and the 5-attempt cap on this activity, but real —
the fix later is an `llm_call_cache` table keyed on `(workflow_id, turn_index)`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import anthropic
from temporalio import activity

from sbda.agent.messages import build_request
from sbda.config import settings
from sbda.core.errors import LLMClientError

_MAX_RATE_LIMIT_SLEEP_S = 60.0


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
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


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


@activity.defn
async def call_claude(input: LLMInput) -> LLMResult:
    client = _get_client()
    request = build_request(input.messages, force_report=input.force_report)

    try:
        message = await asyncio.to_thread(client.messages.create, **request)
    except anthropic.RateLimitError as e:
        retry_after = _extract_retry_after(e)
        sleep_s = min(retry_after, _MAX_RATE_LIMIT_SLEEP_S) if retry_after else 0.0
        if sleep_s > 0:
            await asyncio.sleep(sleep_s)
        raise  # retryable — let Temporal back off further
    except (anthropic.BadRequestError, anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise LLMClientError(str(e)) from e
    except anthropic.APIStatusError:
        raise  # 5xx — retryable
    except anthropic.APIConnectionError:
        raise  # network/timeout — retryable

    return _response_to_result(message)


def _extract_retry_after(exc: "anthropic.RateLimitError") -> float | None:
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
