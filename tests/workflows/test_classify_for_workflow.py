"""Unit tests for `FileAnalysisWorkflow`'s `_classify_for_workflow` helper —
specifically that it correctly categorizes LLM rate-limit/server/connection
errors (instead of falling through to ErrorCategory.INTERNAL) and that an
explicit `non_retryable=True` anywhere in the cause chain (e.g. `call_claude`
exhausting its own per-error-type retry budget) always wins over `classify()`.
"""

from __future__ import annotations

from sbda.core.enums import ErrorCategory
from sbda.temporal.workflows.file_analysis import _classify_for_workflow


class _FakeFailure(Exception):
    def __init__(self, message, type, non_retryable=False, cause=None):
        super().__init__(message)
        self.type = type
        self.non_retryable = non_retryable
        self.__cause__ = cause

    @property
    def cause(self):
        return self.__cause__


def _wrapped_llm_failure(type_name, non_retryable):
    """Mirrors what actually crosses the activity/workflow boundary: an outer
    ApplicationError (carrying `type`/`non_retryable` as raised by
    `call_claude`) wrapping an inner, auto-wrapped one for the original SDK
    exception (which never carries `non_retryable=True`).
    """
    inner = _FakeFailure("boom", type=type_name, non_retryable=False)
    return _FakeFailure("boom", type=type_name, non_retryable=non_retryable, cause=inner)


def test_rate_limit_error_classified_as_llm_category():
    category, retryable = _classify_for_workflow(_wrapped_llm_failure("RateLimitError", False))
    assert category == ErrorCategory.LLM
    assert retryable is True


def test_api_status_error_classified_as_llm_category():
    category, retryable = _classify_for_workflow(_wrapped_llm_failure("APIStatusError", False))
    assert category == ErrorCategory.LLM
    assert retryable is True


def test_api_connection_error_classified_as_llm_category():
    category, retryable = _classify_for_workflow(_wrapped_llm_failure("APIConnectionError", False))
    assert category == ErrorCategory.LLM
    assert retryable is True


def test_budget_exhausted_rate_limit_error_is_not_retryable():
    category, retryable = _classify_for_workflow(_wrapped_llm_failure("RateLimitError", True))
    assert category == ErrorCategory.LLM
    assert retryable is False


def test_budget_exhausted_other_retryable_error_is_not_retryable():
    category, retryable = _classify_for_workflow(_wrapped_llm_failure("APIStatusError", True))
    assert category == ErrorCategory.LLM
    assert retryable is False
