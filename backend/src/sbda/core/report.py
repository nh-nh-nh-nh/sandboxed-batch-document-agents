"""The `write_report` payload schema + validator (SPEC.md §9.3).

Pure logic. The workflow calls ``validate_report`` on the tool input; on
failure the resulting message is returned to the model as an ``is_error``
tool result so it can self-correct — the message must therefore be plain,
non-empty prose naming the offending field, not a stack trace.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as _PydanticValidationError


class Severity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    detail: str
    severity: Severity


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    findings: list[Finding]


class ReportValidationError(Exception):
    """Raised when a `write_report` tool call payload fails schema validation."""


def _format_error(exc: _PydanticValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<report>"
        parts.append(f"{loc}: {err['msg']}")
    return "Invalid report: " + "; ".join(parts)


def validate_report(payload: dict) -> dict:
    """Validate a `write_report` payload against the report schema.

    Returns the normalized report (JSON-serializable dict) on success.
    Raises ``ReportValidationError`` with a human-readable, non-empty
    message naming the offending field(s) on failure.
    """

    try:
        report = Report.model_validate(payload)
    except _PydanticValidationError as e:
        raise ReportValidationError(_format_error(e)) from e

    return report.model_dump(mode="json")
