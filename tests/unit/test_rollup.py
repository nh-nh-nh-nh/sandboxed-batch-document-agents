from __future__ import annotations

import pytest

from sbda.core.enums import FileStatus, SubmissionStatus
from sbda.core.rollup import EmptyRollupError, rollup


def test_all_succeeded():
    result = rollup([FileStatus.SUCCEEDED] * 5)
    assert result.status == SubmissionStatus.SUCCEEDED
    assert (result.succeeded_count, result.failed_count) == (5, 0)


def test_all_failed():
    result = rollup([FileStatus.FAILED] * 5)
    assert result.status == SubmissionStatus.FAILED
    assert (result.succeeded_count, result.failed_count) == (0, 5)


def test_mixed_is_partially_succeeded():
    result = rollup([FileStatus.SUCCEEDED, FileStatus.FAILED])
    assert result.status == SubmissionStatus.PARTIALLY_SUCCEEDED


def test_single_succeeded():
    result = rollup([FileStatus.SUCCEEDED])
    assert result.status == SubmissionStatus.SUCCEEDED


def test_single_failed():
    result = rollup([FileStatus.FAILED])
    assert result.status == SubmissionStatus.FAILED


def test_empty_list_raises():
    with pytest.raises(EmptyRollupError):
        rollup([])


def test_99_succeeded_1_failed():
    statuses = [FileStatus.SUCCEEDED] * 99 + [FileStatus.FAILED]
    result = rollup(statuses)
    assert result.status == SubmissionStatus.PARTIALLY_SUCCEEDED
    assert (result.succeeded_count, result.failed_count) == (99, 1)


def test_1_succeeded_99_failed():
    statuses = [FileStatus.SUCCEEDED] + [FileStatus.FAILED] * 99
    result = rollup(statuses)
    assert result.status == SubmissionStatus.PARTIALLY_SUCCEEDED
    assert (result.succeeded_count, result.failed_count) == (1, 99)


def test_exception_counted_as_failed_not_raised():
    statuses = [FileStatus.SUCCEEDED, RuntimeError("boom")]
    result = rollup(statuses)
    assert result.status == SubmissionStatus.PARTIALLY_SUCCEEDED
    assert result.failed_count == 1


@pytest.mark.parametrize(
    "statuses",
    [
        [FileStatus.SUCCEEDED] * 3,
        [FileStatus.FAILED] * 3,
        [FileStatus.SUCCEEDED, FileStatus.FAILED, RuntimeError("x")],
    ],
)
def test_counts_always_sum_to_input_length(statuses):
    result = rollup(statuses)
    assert result.succeeded_count + result.failed_count == len(statuses)
