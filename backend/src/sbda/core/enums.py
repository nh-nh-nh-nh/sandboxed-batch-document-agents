"""Shared enums (SPEC.md §3.4).

Defined once in `core` (pure, no I/O) and reused by `db.models` for the
Postgres enum columns, so there is a single source of truth.
"""

from __future__ import annotations

import enum


class SubmissionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIALLY_SUCCEEDED = "PARTIALLY_SUCCEEDED"
    FAILED = "FAILED"


class FileStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ErrorCategory(str, enum.Enum):
    VALIDATION = "VALIDATION"
    SANDBOX = "SANDBOX"
    LLM = "LLM"
    TOOL = "TOOL"
    TIMEOUT = "TIMEOUT"
    INTERNAL = "INTERNAL"
