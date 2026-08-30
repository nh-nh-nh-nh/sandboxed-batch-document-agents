"""Shared Temporal constants: task queue, retry policies, timeouts, fairness.

See SPEC.md §6 for the exact tables these are transcribed from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from temporalio.common import Priority, RetryPolicy

from sbda.core.errors import LLMClientError, ValidationError

TASK_QUEUE = "document-analysis"


# --- Workflow input/output shapes (plain dataclasses — Temporal-serializable) ---


@dataclass(frozen=True)
class FileRef:
    file_id: str
    s3_key: str
    original_filename: str
    size_bytes: int


@dataclass(frozen=True)
class SubmissionInput:
    submission_id: str
    tenant_id: str
    files: list[FileRef] = field(default_factory=list)


@dataclass(frozen=True)
class SubmissionResult:
    status: str
    succeeded: int
    failed: int


@dataclass(frozen=True)
class FileInput:
    file_id: str
    submission_id: str
    tenant_id: str
    s3_key: str
    original_filename: str
    size_bytes: int
    sanitized_filename: str


@dataclass(frozen=True)
class FileResult:
    status: str

# --- §6.3 Timeouts ---------------------------------------------------------

SUBMISSION_WORKFLOW_RUN_TIMEOUT = timedelta(hours=4)

FILE_WORKFLOW_RUN_TIMEOUT = timedelta(minutes=30)
FILE_WORKFLOW_SINGLE_ATTEMPT_RUN_TIMEOUT = timedelta(minutes=15)

CALL_CLAUDE_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)
CALL_CLAUDE_SCHEDULE_TO_START_TIMEOUT = timedelta(minutes=30)

PROVISION_SANDBOX_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)
EXEC_TOOL_START_TO_CLOSE_TIMEOUT = timedelta(minutes=3)
TERMINATE_SANDBOX_START_TO_CLOSE_TIMEOUT = timedelta(minutes=1)

MODAL_SANDBOX_TIMEOUT_S = 1200  # 20 minutes wall clock
MODAL_EXEC_TIMEOUT_S = 120

# --- §6.4 Retry policies -----------------------------------------------------

# Names referenced in non_retryable_error_types are matched by Temporal against
# the *class name* of the raised (and possibly wrapped) exception, so both
# `ValidationError` and `LLMClientError` must be raised (or wrapped as an
# ApplicationError with a matching `type=`) for these policies to bite.
CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    non_retryable_error_types=[ValidationError.__name__],
)

CALL_CLAUDE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=5,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    non_retryable_error_types=[LLMClientError.__name__],
)

PROVISION_SANDBOX_RETRY_POLICY = RetryPolicy(maximum_attempts=3)

# Transport-level retries only — a non-zero exit from the tool code itself is a
# normal (non-exceptional) activity result, not a failure Temporal retries.
EXEC_TOOL_RETRY_POLICY = RetryPolicy(maximum_attempts=2)

# Must not leak a sandbox: retried aggressively, for a long time.
TERMINATE_SANDBOX_RETRY_POLICY = RetryPolicy(
    maximum_attempts=5,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
)

# The read model must converge — unlimited attempts.
MARK_DB_RETRY_POLICY = RetryPolicy(
    maximum_attempts=0,  # 0 == unlimited in Temporal's RetryPolicy
    maximum_interval=timedelta(seconds=30),
)

# Short aliases used by tests/unit/test_errors.py (SPEC.md §14.1).
CHILD_RETRY = CHILD_WORKFLOW_RETRY_POLICY
CALL_CLAUDE_RETRY = CALL_CLAUDE_RETRY_POLICY


def fairness_priority(tenant_id: str) -> Priority:
    """§6.1 — fairness key is the tenant id, equal weight."""
    return Priority(fairness_key=str(tenant_id), fairness_weight=1.0)
