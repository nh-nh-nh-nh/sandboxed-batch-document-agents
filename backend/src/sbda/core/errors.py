# STUB — owned by the backend-foundation slice (see SPEC.md §14.1 `test_errors.py`, §2).
#
# Minimal implementation of the exception hierarchy and the
# exception -> (error_category, retryable) classifier described in SPEC.md.
# The temporal/agent slice imports `from sbda.core.errors import classify,
# ValidationError, LLMClientError, SandboxGoneError` and depends on the exact
# names/behavior below. Reconcile against the backend-foundation PR's real
# `core/errors.py`.

from __future__ import annotations

from sbda.db.models import ErrorCategory


class ValidationError(Exception):
    """Non-retryable: the input itself is invalid (bad file, malformed batch)."""


class LLMClientError(Exception):
    """Non-retryable: Anthropic 4xx (bad request / auth / permission denied)."""


class SandboxGoneError(Exception):
    """Retryable: the Modal sandbox is unreachable or has terminated."""


class ToolExecutionError(Exception):
    """Not used for normal non-zero tool exit (that's a result, not a raise)."""


def classify(exc: BaseException) -> tuple[ErrorCategory, bool]:
    """Map an exception to (error_category, retryable) per SPEC.md §14.1."""

    if isinstance(exc, ValidationError):
        return ErrorCategory.VALIDATION, False
    if isinstance(exc, LLMClientError):
        return ErrorCategory.LLM, False
    if isinstance(exc, SandboxGoneError):
        return ErrorCategory.SANDBOX, True

    name = type(exc).__name__
    if name in ("RateLimitError", "APIStatusError", "APIConnectionError"):
        return ErrorCategory.LLM, True
    if name == "NotFoundError":
        return ErrorCategory.SANDBOX, True
    if name == "TimeoutError" or isinstance(exc, TimeoutError):
        return ErrorCategory.TIMEOUT, True

    return ErrorCategory.INTERNAL, True
