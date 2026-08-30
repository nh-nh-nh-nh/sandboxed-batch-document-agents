# STUB — owned by the backend-foundation slice (see SPEC.md §9.3, §14.1 `test_report.py`).
#
# Report schema + validator. Reconcile against the backend-foundation PR's
# real `core/report.py`.

from __future__ import annotations

ALLOWED_SEVERITIES = {"info", "warning", "critical"}


class ReportValidationError(Exception):
    pass


def validate_report(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ReportValidationError("report payload must be an object")

    allowed_keys = {"summary", "findings"}
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ReportValidationError(f"unexpected field(s): {', '.join(sorted(extra))}")

    if "summary" not in payload:
        raise ReportValidationError("missing required field: summary")
    if "findings" not in payload:
        raise ReportValidationError("missing required field: findings")

    summary = payload["summary"]
    if not isinstance(summary, str):
        raise ReportValidationError("summary must be a string")

    findings = payload["findings"]
    if not isinstance(findings, list):
        raise ReportValidationError("findings must be a list")

    normalized_findings = []
    for i, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise ReportValidationError(f"findings[{i}] must be an object")
        allowed_finding_keys = {"title", "detail", "severity"}
        extra_f = set(finding.keys()) - allowed_finding_keys
        if extra_f:
            raise ReportValidationError(
                f"findings[{i}] has unexpected field(s): {', '.join(sorted(extra_f))}"
            )
        for field in ("title", "detail", "severity"):
            if field not in finding:
                raise ReportValidationError(f"findings[{i}] missing required field: {field}")
        if finding["severity"] not in ALLOWED_SEVERITIES:
            raise ReportValidationError(
                f"findings[{i}].severity must be one of {sorted(ALLOWED_SEVERITIES)}"
            )
        normalized_findings.append(
            {
                "title": finding["title"],
                "detail": finding["detail"],
                "severity": finding["severity"],
            }
        )

    return {"summary": summary, "findings": normalized_findings}
