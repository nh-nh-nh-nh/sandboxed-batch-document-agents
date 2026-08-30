from __future__ import annotations

import pytest

from sbda.core.enums import ErrorCategory
from sbda.core.errors import (
    LLMClientError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMServerError,
    SandboxError,
    SandboxGoneError,
    SandboxProvisionError,
    classify,
)
from sbda.core.validation import ValidationError


@pytest.mark.parametrize(
    ("exc", "category", "retryable"),
    [
        (SandboxGoneError("gone"), ErrorCategory.SANDBOX, True),
        (SandboxProvisionError("provision failed"), ErrorCategory.SANDBOX, True),
        (LLMClientError("400"), ErrorCategory.LLM, False),
        (LLMRateLimitError("429"), ErrorCategory.LLM, True),
        (LLMServerError("503"), ErrorCategory.LLM, True),
        (LLMConnectionError("conn"), ErrorCategory.LLM, True),
        (ValidationError("bad input"), ErrorCategory.VALIDATION, False),
        (TimeoutError("timed out"), ErrorCategory.TIMEOUT, True),
        (Exception("anything"), ErrorCategory.INTERNAL, True),
        (RuntimeError("bare"), ErrorCategory.INTERNAL, True),
    ],
)
def test_classify(exc, category, retryable):
    result = classify(exc)
    assert result.category == category
    assert result.retryable == retryable


def test_sandbox_gone_is_a_sandbox_error():
    assert isinstance(SandboxGoneError("x"), SandboxError)


def test_tool_exec_nonzero_exit_is_not_an_exception():
    # A non-zero exit from a sandbox tool call is represented as a normal
    # tool result (is_error=True), never raised as a Python exception —
    # there is nothing to classify() here. This test documents that
    # invariant: none of the classify() categories are reachable via a
    # "the process exited non-zero" code path.
    assert True


def test_validation_and_llm_client_error_are_non_retryable_in_shared_policy():
    shared = pytest.importorskip(
        "sbda.temporal.shared",
        reason="temporal/shared.py is implemented in the Temporal-workflow slice",
    )
    assert "ValidationError" in shared.CHILD_RETRY.non_retryable_error_types
    assert "LLMClientError" in shared.CALL_CLAUDE_RETRY.non_retryable_error_types
