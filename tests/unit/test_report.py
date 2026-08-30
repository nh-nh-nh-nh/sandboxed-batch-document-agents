from __future__ import annotations

import pytest

from sbda.core.report import ReportValidationError, validate_report


def test_valid_with_3_findings():
    payload = {
        "summary": "Three findings.",
        "findings": [
            {"title": "a", "detail": "d1", "severity": "info"},
            {"title": "b", "detail": "d2", "severity": "warning"},
            {"title": "c", "detail": "d3", "severity": "critical"},
        ],
    }
    result = validate_report(payload)
    assert result["summary"] == "Three findings."
    assert len(result["findings"]) == 3


def test_valid_empty_findings():
    payload = {"summary": "Clean file.", "findings": []}
    result = validate_report(payload)
    assert result["findings"] == []


def test_missing_summary_names_field():
    with pytest.raises(ReportValidationError) as exc_info:
        validate_report({"findings": []})
    assert "summary" in str(exc_info.value)


def test_missing_findings():
    with pytest.raises(ReportValidationError) as exc_info:
        validate_report({"summary": "x"})
    assert "findings" in str(exc_info.value)


def test_invalid_severity_value():
    payload = {
        "summary": "x",
        "findings": [{"title": "a", "detail": "d", "severity": "SEVERE"}],
    }
    with pytest.raises(ReportValidationError) as exc_info:
        validate_report(payload)
    msg = str(exc_info.value)
    assert "info" in msg and "warning" in msg and "critical" in msg


def test_severity_wrong_case_rejected():
    payload = {
        "summary": "x",
        "findings": [{"title": "a", "detail": "d", "severity": "INFO"}],
    }
    with pytest.raises(ReportValidationError):
        validate_report(payload)


def test_extra_top_level_key_rejected():
    payload = {"summary": "x", "findings": [], "extra": "nope"}
    with pytest.raises(ReportValidationError):
        validate_report(payload)


def test_extra_key_inside_finding_rejected():
    payload = {
        "summary": "x",
        "findings": [{"title": "a", "detail": "d", "severity": "info", "extra": "nope"}],
    }
    with pytest.raises(ReportValidationError):
        validate_report(payload)


def test_summary_not_a_string_rejected():
    with pytest.raises(ReportValidationError):
        validate_report({"summary": 123, "findings": []})


def test_findings_not_a_list_rejected():
    with pytest.raises(ReportValidationError):
        validate_report({"summary": "x", "findings": "nope"})


def test_finding_missing_detail_rejected():
    payload = {"summary": "x", "findings": [{"title": "a", "severity": "info"}]}
    with pytest.raises(ReportValidationError) as exc_info:
        validate_report(payload)
    assert "detail" in str(exc_info.value)


def test_500_findings_accepted():
    findings = [{"title": f"t{i}", "detail": f"d{i}", "severity": "info"} for i in range(500)]
    payload = {"summary": "x", "findings": findings}
    result = validate_report(payload)
    assert len(result["findings"]) == 500


def test_summary_with_markdown_newlines_emoji_stored_verbatim():
    summary = "# Title\nSome **bold** text 🎉\nline2"
    payload = {"summary": summary, "findings": []}
    result = validate_report(payload)
    assert result["summary"] == summary


def test_rejection_message_is_non_empty_and_names_field():
    with pytest.raises(ReportValidationError) as exc_info:
        validate_report({"findings": []})
    msg = str(exc_info.value)
    assert len(msg) > 0
    assert "summary" in msg
