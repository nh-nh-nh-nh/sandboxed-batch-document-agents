"""Exception -> (error_category, retryable) classifier (SPEC.md §14.1).

Pure logic: no imports from Temporal, Modal, boto3, or the Anthropic SDK.
The activity layer (implemented in another slice) is responsible for
catching the real SDK exceptions (``modal.exception.NotFoundError``,
``anthropic.RateLimitError``, etc.) and re-raising them as one of the
exception types defined here, so that this classifier — and the workflow
control flow that depends on it — never needs to know about those SDKs.
"""

from __future__ import annotations

from typing import NamedTuple

from sbda.core.enums import ErrorCategory
from sbda.core.validation import ValidationError

__all__ = [
    "ErrorClassification",
    "LLMClientError",
    "LLMConnectionError",
    "LLMRateLimitError",
    "LLMServerError",
    "SandboxError",
    "SandboxGoneError",
    "SandboxProvisionError",
    "ToolExecutionError",
    "ValidationError",
    "classify",
]


class SandboxError(Exception):
    """Base class for Modal sandbox failures. Always retryable (§6.4)."""


class SandboxGoneError(SandboxError):
    """The sandbox disappeared mid-loop or could not be resolved by id (§8.3)."""


class SandboxProvisionError(SandboxError):
    """Sandbox provisioning failed."""


class LLMClientError(Exception):
    """A non-retryable Anthropic API error (4xx: bad request / auth / permission)."""


class LLMRateLimitError(Exception):
    """Anthropic 429. Retryable."""


class LLMServerError(Exception):
    """Anthropic 5xx. Retryable."""


class LLMConnectionError(Exception):
    """Anthropic connection/timeout error. Retryable."""


class ToolExecutionError(Exception):
    """Reserved for genuine tool-activity transport failures (not a non-zero
    exit code, which is a normal tool result, not an exception — §9.4)."""


class ErrorClassification(NamedTuple):
    category: ErrorCategory
    retryable: bool


def classify(exc: BaseException) -> ErrorClassification:
    """Classify an exception into (error_category, retryable).

    Order matters: subclasses are checked before their bases, and the
    LLM-specific types are checked before the generic fallback.
    """

    if isinstance(exc, ValidationError):
        return ErrorClassification(ErrorCategory.VALIDATION, False)

    if isinstance(exc, SandboxError):
        return ErrorClassification(ErrorCategory.SANDBOX, True)

    if isinstance(exc, LLMClientError):
        return ErrorClassification(ErrorCategory.LLM, False)

    if isinstance(exc, (LLMRateLimitError, LLMServerError, LLMConnectionError)):
        return ErrorClassification(ErrorCategory.LLM, True)

    if isinstance(exc, ToolExecutionError):
        return ErrorClassification(ErrorCategory.TOOL, False)

    if isinstance(exc, TimeoutError):
        return ErrorClassification(ErrorCategory.TIMEOUT, True)

    return ErrorClassification(ErrorCategory.INTERNAL, True)
