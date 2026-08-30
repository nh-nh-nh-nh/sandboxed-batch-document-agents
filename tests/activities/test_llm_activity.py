"""Activity-body tests for `sbda.temporal.activities.llm.call_claude`, with
the Anthropic client patched. SPEC.md §14.2.
"""

from __future__ import annotations

import dataclasses
import json
import types
from datetime import timedelta

import anthropic
import httpx2
import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from sbda.core.errors import LLMClientError
from sbda.temporal.activities import llm as llm_mod


def _request():
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _response(status, headers=None):
    return httpx2.Response(status, headers=headers or {}, request=_request())


class FakeMessages:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._response


class FakeClient:
    def __init__(self, response=None, exc=None):
        self.messages = FakeMessages(response=response, exc=exc)


def _fake_message(stop_reason="end_turn", content=None, usage=None):
    if content is None:
        content = [types.SimpleNamespace(model_dump=lambda: {"type": "text", "text": "hi"})]
    usage_obj = types.SimpleNamespace(
        model_dump=lambda: usage
        or {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3}
    )
    return types.SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage_obj)


@pytest.fixture(autouse=True)
def default_api_key(monkeypatch):
    from sbda.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(llm_mod, "_get_client", lambda: client)


def _input(**kwargs):
    return llm_mod.LLMInput(messages=[{"role": "user", "content": "hi"}], **kwargs)


def _rate_limit_error(retry_after=None):
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return anthropic.RateLimitError("rate limited", response=_response(429, headers), body=None)


async def test_normal_response_converts_to_json_serializable_dataclass(monkeypatch):
    message = _fake_message()
    client = FakeClient(response=message)
    _patch_client(monkeypatch, client)

    result = await llm_mod.call_claude(_input())

    # No SDK objects survive — the whole thing must be JSON-serializable.
    json.dumps(
        {"content": result.content, "stop_reason": result.stop_reason, "usage": result.usage}
    )
    assert result.stop_reason == "end_turn"
    assert result.usage["input_tokens"] == 10


async def test_rate_limit_error_sets_next_retry_delay_from_retry_after(monkeypatch):
    exc = _rate_limit_error(retry_after="30")
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    with pytest.raises(ApplicationError) as exc_info:
        await llm_mod.call_claude(_input())

    err = exc_info.value
    assert err.type == "RateLimitError"
    assert err.non_retryable is False
    assert err.next_retry_delay == timedelta(seconds=30)


async def test_rate_limit_error_next_retry_delay_capped(monkeypatch):
    exc = _rate_limit_error(retry_after="120")
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    with pytest.raises(ApplicationError) as exc_info:
        await llm_mod.call_claude(_input())

    assert exc_info.value.next_retry_delay == timedelta(seconds=60)


async def test_rate_limit_error_retry_after_zero_retries_immediately(monkeypatch):
    exc = _rate_limit_error(retry_after="0")
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    with pytest.raises(ApplicationError) as exc_info:
        await llm_mod.call_claude(_input())

    assert exc_info.value.next_retry_delay == timedelta(seconds=0)


async def test_rate_limit_error_negative_retry_after_falls_back_to_default_backoff(monkeypatch):
    exc = _rate_limit_error(retry_after="-5")
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    with pytest.raises(ApplicationError) as exc_info:
        await llm_mod.call_claude(_input())

    assert exc_info.value.next_retry_delay is None


async def test_api_status_error_503_reraises_as_retryable(monkeypatch):
    exc = anthropic.APIStatusError("service unavailable", response=_response(503), body=None)
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    with pytest.raises(ApplicationError) as exc_info:
        await llm_mod.call_claude(_input())

    err = exc_info.value
    assert err.type == "APIStatusError"
    assert err.non_retryable is False
    assert err.next_retry_delay is None


async def test_api_connection_error_reraises_as_retryable(monkeypatch):
    exc = anthropic.APIConnectionError(request=_request())
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    with pytest.raises(ApplicationError) as exc_info:
        await llm_mod.call_claude(_input())

    err = exc_info.value
    assert err.type == "APIConnectionError"
    assert err.non_retryable is False
    assert err.next_retry_delay is None


@pytest.mark.parametrize(
    "exc_cls,status",
    [
        (anthropic.BadRequestError, 400),
        (anthropic.AuthenticationError, 401),
        (anthropic.PermissionDeniedError, 403),
    ],
)
async def test_4xx_errors_raise_llm_client_error_non_retryable(monkeypatch, exc_cls, status):
    exc = exc_cls("bad", response=_response(status), body=None)
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    with pytest.raises(LLMClientError):
        await llm_mod.call_claude(_input())


async def test_rate_limit_not_swallowed_by_generic_status_handler(monkeypatch):
    # A RateLimitError IS an APIStatusError subclass; the handler order must
    # catch it on the specific branch, not the generic 5xx branch, so the
    # retry-after-derived next_retry_delay still gets set.
    assert issubclass(anthropic.RateLimitError, anthropic.APIStatusError)

    exc = _rate_limit_error(retry_after="1")
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    with pytest.raises(ApplicationError) as exc_info:
        await llm_mod.call_claude(_input())

    err = exc_info.value
    assert err.type == "RateLimitError"
    assert err.next_retry_delay == timedelta(seconds=1)


async def test_stop_reason_passed_through_untouched(monkeypatch):
    message = _fake_message(stop_reason="tool_use")
    client = FakeClient(response=message)
    _patch_client(monkeypatch, client)

    result = await llm_mod.call_claude(_input())
    assert result.stop_reason == "tool_use"


async def test_force_report_true_passed_into_request(monkeypatch):
    message = _fake_message()
    client = FakeClient(response=message)
    _patch_client(monkeypatch, client)

    await llm_mod.call_claude(_input(force_report=True))
    assert client.messages.calls[0]["tool_choice"] == {"type": "tool", "name": "write_report"}


def _env_with_heartbeat_state(attempt, rate_limit_attempts, other_retryable_attempts):
    env = ActivityEnvironment()
    env.info = dataclasses.replace(
        ActivityEnvironment.default_info(),
        attempt=attempt,
        heartbeat_details=[
            {
                "rate_limit_attempts": rate_limit_attempts,
                "other_retryable_attempts": other_retryable_attempts,
            }
        ],
    )
    heartbeats = []
    env.on_heartbeat = lambda *args: heartbeats.append(args[0])
    return env, heartbeats


async def test_rate_limit_budget_exhausted_raises_non_retryable(monkeypatch):
    exc = anthropic.RateLimitError("rate limited", response=_response(429), body=None)
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    env, heartbeats = _env_with_heartbeat_state(
        attempt=51, rate_limit_attempts=50, other_retryable_attempts=0
    )

    with pytest.raises(ApplicationError) as exc_info:
        await env.run(llm_mod.call_claude, _input())

    err = exc_info.value
    assert err.type == "RateLimitError"
    assert err.non_retryable is True
    assert heartbeats == []  # budget exhausted, no further heartbeat


async def test_other_retryable_budget_exhausted_raises_non_retryable(monkeypatch):
    exc = anthropic.APIStatusError("service unavailable", response=_response(503), body=None)
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    env, heartbeats = _env_with_heartbeat_state(
        attempt=4, rate_limit_attempts=0, other_retryable_attempts=3
    )

    with pytest.raises(ApplicationError) as exc_info:
        await env.run(llm_mod.call_claude, _input())

    err = exc_info.value
    assert err.type == "APIStatusError"
    assert err.non_retryable is True
    assert heartbeats == []


async def test_rate_limit_attempts_restored_from_heartbeat_and_incremented(monkeypatch):
    exc = _rate_limit_error(retry_after="5")
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    env, heartbeats = _env_with_heartbeat_state(
        attempt=2, rate_limit_attempts=1, other_retryable_attempts=0
    )

    with pytest.raises(ApplicationError):
        await env.run(llm_mod.call_claude, _input())

    assert heartbeats == [{"rate_limit_attempts": 2, "other_retryable_attempts": 0}]


async def test_other_retryable_counter_independent_of_rate_limit_counter(monkeypatch):
    exc = anthropic.APIStatusError("service unavailable", response=_response(503), body=None)
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    # 10 rate-limit attempts already spent — well under the 50 budget, but
    # tracked on a completely separate counter from other-retryable errors.
    env, heartbeats = _env_with_heartbeat_state(
        attempt=11, rate_limit_attempts=10, other_retryable_attempts=0
    )

    with pytest.raises(ApplicationError) as exc_info:
        await env.run(llm_mod.call_claude, _input())

    assert exc_info.value.non_retryable is False  # only 1 of 3 other-retryable attempts used
    assert heartbeats == [{"rate_limit_attempts": 10, "other_retryable_attempts": 1}]


def test_get_client_disables_sdk_auto_retries(monkeypatch, default_api_key):
    captured = {}

    class _FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_mod.anthropic, "Anthropic", _FakeAnthropic)
    llm_mod._get_client()

    assert captured["max_retries"] == 0
