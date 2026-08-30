"""`mark_*` DB activities — the read-model writers. See SPEC.md §7.1, §7.2.

Every activity here is an idempotent upsert: calling it twice must leave
identical rows (§14.2 `test_db_activities.py`), because the `mark_*` retry
policy is unlimited attempts (`temporal/shared.py::MARK_DB_RETRY_POLICY`) —
the read model must converge no matter how many times a `mark_*` call is
retried after a transport failure whose write actually succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio import activity

from sbda.config import settings
from sbda.db.models import ErrorCategory, File, FileStatus, Submission, SubmissionStatus

_ERROR_MESSAGE_MAX_CHARS = 2000

_engine = None
_sessionmaker: async_sessionmaker | None = None


def _get_sessionmaker() -> async_sessionmaker:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = create_async_engine(settings.database_url)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


@dataclass
class MarkSubmissionRunningInput:
    submission_id: str


@dataclass
class MarkSubmissionTerminalInput:
    submission_id: str
    status: str  # SubmissionStatus value
    succeeded_count: int
    failed_count: int
    error_message: str | None = None


@dataclass
class MarkFileRunningInput:
    file_id: str
    attempt: int = 1


@dataclass
class MarkFileSucceededInput:
    file_id: str
    report: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    turn_count: int = 0


@dataclass
class MarkFileFailedInput:
    file_id: str
    error_category: str  # ErrorCategory value
    error_message: str


def _truncate_error_message(message: str | None) -> str | None:
    if message is None:
        return None
    return message[:_ERROR_MESSAGE_MAX_CHARS]


def _now_naive_utc() -> datetime:
    """`started_at`/`finished_at` are TIMESTAMP WITHOUT TIME ZONE columns
    (like every other timestamp in this schema) — strip tzinfo so asyncpg
    doesn't reject a tz-aware value against a naive column."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@activity.defn
async def mark_submission_running(input: MarkSubmissionRunningInput) -> None:
    session_factory = _get_sessionmaker()
    async with session_factory() as session:
        await session.execute(
            update(Submission)
            .where(Submission.id == input.submission_id)
            .values(status=SubmissionStatus.RUNNING)
        )
        await session.commit()


@activity.defn
async def mark_submission_terminal(input: MarkSubmissionTerminalInput) -> None:
    session_factory = _get_sessionmaker()
    async with session_factory() as session:
        await session.execute(
            update(Submission)
            .where(Submission.id == input.submission_id)
            .values(
                status=SubmissionStatus(input.status),
                succeeded_count=input.succeeded_count,
                failed_count=input.failed_count,
                error_message=_truncate_error_message(input.error_message),
            )
        )
        # Repair pass: any file row still PENDING/RUNNING for this submission
        # means its child workflow died without writing its own terminal row
        # (§7.1). Mark it FAILED/INTERNAL so the UI never shows a permanently
        # spinning row.
        await session.execute(
            update(File)
            .where(
                File.submission_id == input.submission_id,
                File.status.in_([FileStatus.PENDING, FileStatus.RUNNING]),
            )
            .values(
                status=FileStatus.FAILED,
                error_category=ErrorCategory.INTERNAL,
                error_message="submission finished but this file never reached a terminal state",
            )
        )
        await session.commit()


@activity.defn
async def mark_file_running(input: MarkFileRunningInput) -> None:
    session_factory = _get_sessionmaker()
    async with session_factory() as session:
        await session.execute(
            update(File)
            .where(File.id == input.file_id)
            .values(
                status=FileStatus.RUNNING,
                attempt_count=input.attempt,
                started_at=_now_naive_utc(),
            )
        )
        await session.commit()


@activity.defn
async def mark_file_succeeded(input: MarkFileSucceededInput) -> None:
    session_factory = _get_sessionmaker()
    async with session_factory() as session:
        await session.execute(
            update(File)
            .where(File.id == input.file_id)
            .values(
                status=FileStatus.SUCCEEDED,
                report=input.report,
                input_tokens=input.input_tokens,
                output_tokens=input.output_tokens,
                cache_read_tokens=input.cache_read_tokens,
                turn_count=input.turn_count,
                finished_at=_now_naive_utc(),
            )
        )
        await session.commit()


@activity.defn
async def mark_file_failed(input: MarkFileFailedInput) -> None:
    session_factory = _get_sessionmaker()
    async with session_factory() as session:
        await session.execute(
            update(File)
            .where(File.id == input.file_id)
            .values(
                status=FileStatus.FAILED,
                error_category=ErrorCategory(input.error_category),
                error_message=_truncate_error_message(input.error_message),
                finished_at=_now_naive_utc(),
            )
        )
        await session.commit()
