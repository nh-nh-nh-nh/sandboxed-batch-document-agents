"""Batch upload validation. Pure logic — no I/O.

Mirrors the rules in SPEC.md §5.2 step 2-3 and the table in §14.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".csv", ".tsv", ".xlsx", ".xls", ".xlsm"})

DEFAULT_MAX_FILES_PER_SUBMISSION = 100
DEFAULT_MAX_FILE_BYTES = 1_048_576
DEFAULT_MAX_SUBMISSION_BYTES = 104_857_600


class ValidationError(Exception):
    """Base class for all core validation errors. Non-retryable (§14.1)."""


class NoFilesError(ValidationError):
    def __init__(self) -> None:
        super().__init__("At least one file is required")


class TooManyFilesError(ValidationError):
    def __init__(self, count: int, max_files: int) -> None:
        self.count = count
        self.max_files = max_files
        super().__init__(f"Too many files: {count} exceeds the maximum of {max_files}")


class UnsupportedExtensionError(ValidationError):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        super().__init__(f"Unsupported file extension for {filename!r}")


class FileTooLargeError(ValidationError):
    def __init__(self, filename: str, size_bytes: int, max_bytes: int) -> None:
        self.filename = filename
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes
        super().__init__(
            f"File {filename!r} is {size_bytes} bytes, exceeding the per-file "
            f"cap of {max_bytes} bytes"
        )


class SubmissionTooLargeError(ValidationError):
    def __init__(self, total_bytes: int, max_bytes: int) -> None:
        self.total_bytes = total_bytes
        self.max_bytes = max_bytes
        super().__init__(
            f"Submission totals {total_bytes} bytes, exceeding the cap of {max_bytes} bytes"
        )


@dataclass(frozen=True)
class FileMeta:
    """Minimal description of one uploaded file, for validation purposes."""

    filename: str
    size_bytes: int


def get_extension(filename: str) -> str:
    """Return the final, lowercased suffix of a filename.

    Only the final suffix counts (``report.xlsx.exe`` -> ``.exe``). A filename
    with no stem before a leading dot (``.csv``) has no suffix, per
    ``pathlib`` semantics, and is therefore rejected as unsupported.
    """

    return PurePosixPath(filename).suffix.lower()


def validate_extension(filename: str) -> None:
    ext = get_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedExtensionError(filename)


def validate_batch(
    files: list[FileMeta],
    *,
    max_files: int = DEFAULT_MAX_FILES_PER_SUBMISSION,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_submission_bytes: int = DEFAULT_MAX_SUBMISSION_BYTES,
) -> None:
    """Validate a batch of files per SPEC.md §5.2 step 2.

    Raises the first violation found. Order: file count, then extensions
    (in order), then per-file size, then total submission size.
    """

    if len(files) == 0:
        raise NoFilesError()
    if len(files) > max_files:
        raise TooManyFilesError(len(files), max_files)

    for f in files:
        validate_extension(f.filename)

    for f in files:
        if f.size_bytes > max_file_bytes:
            raise FileTooLargeError(f.filename, f.size_bytes, max_file_bytes)

    total = sum(f.size_bytes for f in files)
    if total > max_submission_bytes:
        raise SubmissionTooLargeError(total, max_submission_bytes)
