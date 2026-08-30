"""Activity-body tests for `sbda.temporal.activities.llm.call_claude`, with
the Anthropic client patched. SPEC.md §14.2.
"""

from __future__ import annotations

import json
import types

import anthropic
import httpx2
import pytest

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
    content = content if content is not None else [types.SimpleNamespace(model_dump=lambda: {"type": "text", "text": "hi"})]
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


async def test_normal_response_converts_to_json_serializable_dataclass(monkeypatch):
    message = _fake_message()
    client = FakeClient(response=message)
    _patch_client(monkeypatch, client)

    result = await llm_mod.call_claude(llm_mod.LLMInput(messages=[{"role": "user", "content": "hi"}]))

    # No SDK objects survive — the whole thing must be JSON-serializable.
    json.dumps({"content": result.content, "stop_reason": result.stop_reason, "usage": result.usage})
    assert result.stop_reason == "end_turn"
    assert result.usage["input_tokens"] == 10


async def test_rate_limit_error_sleeps_at_most_60s_then_reraises(monkeypatch):
    exc = anthropic.RateLimitError("rate limited", response=_response(429, {"retry-after": "120"}), body=None)
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(llm_mod.asyncio, "sleep", fake_sleep)

    with pytest.raises(anthropic.RateLimitError):
        await llm_mod.call_claude(llm_mod.LLMInput(messages=[{"role": "user", "content": "hi"}]))

    assert slept == [60.0]  # capped at 60s even though retry-after said 120


async def test_api_status_error_503_reraises_as_retryable(monkeypatch):
    exc = anthropic.APIStatusError("service unavailable", response=_response(503), body=None)
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    with pytest.raises(anthropic.APIStatusError):
        await llm_mod.call_claude(llm_mod.LLMInput(messages=[{"role": "user", "content": "hi"}]))


async def test_api_connection_error_reraises_as_retryable(monkeypatch):
    exc = anthropic.APIConnectionError(request=_request())
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    with pytest.raises(anthropic.APIConnectionError):
        await llm_mod.call_claude(llm_mod.LLMInput(messages=[{"role": "user", "content": "hi"}]))


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
        await llm_mod.call_claude(llm_mod.LLMInput(messages=[{"role": "user", "content": "hi"}]))


async def test_rate_limit_not_swallowed_by_generic_status_handler(monkeypatch):
    # A RateLimitError IS an APIStatusError subclass; the handler order must
    # catch it on the specific branch, not the generic 5xx branch, so the
    # retry-after sleep still happens.
    assert issubclass(anthropic.RateLimitError, anthropic.APIStatusError)

    exc = anthropic.RateLimitError("rate limited", response=_response(429, {"retry-after": "1"}), body=None)
    client = FakeClient(exc=exc)
    _patch_client(monkeypatch, client)

    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(llm_mod.asyncio, "sleep", fake_sleep)

    with pytest.raises(anthropic.RateLimitError):
        await llm_mod.call_claude(llm_mod.LLMInput(messages=[{"role": "user", "content": "hi"}]))

    assert slept == [1.0]


async def test_stop_reason_passed_through_untouched(monkeypatch):
    message = _fake_message(stop_reason="tool_use")
    client = FakeClient(response=message)
    _patch_client(monkeypatch, client)

    result = await llm_mod.call_claude(llm_mod.LLMInput(messages=[{"role": "user", "content": "hi"}]))
    assert result.stop_reason == "tool_use"


async def test_force_report_true_passed_into_request(monkeypatch):
    message = _fake_message()
    client = FakeClient(response=message)
    _patch_client(monkeypatch, client)

    await llm_mod.call_claude(llm_mod.LLMInput(messages=[{"role": "user", "content": "hi"}], force_report=True))
    assert client.messages.calls[0]["tool_choice"] == {"type": "tool", "name": "write_report"}
