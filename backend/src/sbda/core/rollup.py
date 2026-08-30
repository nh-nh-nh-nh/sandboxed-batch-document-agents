# STUB — owned by the backend-foundation slice (see SPEC.md §3.4, §7.1, §14.1 `test_rollup.py`).
#
# Pure fan-in decision function used by SubmissionWorkflow. Reconcile against
# the backend-foundation PR's real `core/rollup.py`.

from __future__ import annotations

from dataclasses import dataclass

from sbda.db.models import FileStatus, SubmissionStatus


@dataclass(frozen=True)
class RollupResult:
    status: SubmissionStatus
    succeeded: int
    failed: int


def rollup(statuses: list) -> RollupResult:
    """Compute submission status from child statuses/exceptions.

    Each element of `statuses` is either a `FileStatus` (or the string
    "SUCCEEDED"/"FAILED") or an exception instance (counted as failed).
    """
    if not statuses:
        raise ValueError("rollup() called with an empty statuses list")

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

    total = succeeded + failed
    assert total == len(statuses)

    if failed == 0:
        status = SubmissionStatus.SUCCEEDED
    elif succeeded == 0:
        status = SubmissionStatus.FAILED
    else:
        status = SubmissionStatus.PARTIALLY_SUCCEEDED

    return RollupResult(status=status, succeeded=succeeded, failed=failed)
