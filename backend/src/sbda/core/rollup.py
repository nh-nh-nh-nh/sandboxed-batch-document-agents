"""Fan-in rollup: child file statuses -> submission status (SPEC.md §3.4, §7.1).

Pure function: no I/O, no Temporal, no db access.
"""

from __future__ import annotations

from dataclasses import dataclass

from sbda.core.enums import FileStatus, SubmissionStatus


class EmptyRollupError(Exception):
    """An empty submission is unreachable and must not silently succeed."""

    def __init__(self) -> None:
        super().__init__("Cannot roll up an empty list of file statuses")


@dataclass(frozen=True)
class RollupResult:
    status: SubmissionStatus
    succeeded_count: int
    failed_count: int


def rollup(statuses: list) -> RollupResult:
    """Compute the submission-level terminal status from child results.

    Each element of ``statuses`` is either a ``FileStatus`` (or the string
    value of one) or an exception instance — an exception is treated exactly
    like a ``FAILED`` result, mirroring ``asyncio.gather(return_exceptions=True)``
    in the parent workflow (§7.1).
    """

    if len(statuses) == 0:
        raise EmptyRollupError()

    succeeded = 0
    failed = 0
    for s in statuses:
        if isinstance(s, BaseException):
            failed += 1
            continue
        value = s.value if isinstance(s, FileStatus) else s
        if value == FileStatus.SUCCEEDED.value:
            succeeded += 1
        else:
            failed += 1

    assert succeeded + failed == len(statuses)

    if failed == 0:
        status = SubmissionStatus.SUCCEEDED
    elif succeeded == 0:
        status = SubmissionStatus.FAILED
    else:
        status = SubmissionStatus.PARTIALLY_SUCCEEDED

    return RollupResult(status=status, succeeded_count=succeeded, failed_count=failed)
