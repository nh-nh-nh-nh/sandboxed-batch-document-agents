"""Smoke tests for `sbda.temporal.worker` — the fail-fast credential check and
the activity/workflow wiring. No real Temporal connection is made.
"""

from __future__ import annotations

import pytest

from sbda.config import settings
from sbda.temporal import worker as worker_mod


@pytest.fixture(autouse=True)
def restore_settings(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "key")
    monkeypatch.setattr(settings, "modal_token_id", "id")
    monkeypatch.setattr(settings, "modal_token_secret", "secret")


def test_check_required_credentials_passes_when_all_present():
    worker_mod._check_required_credentials()  # must not raise


@pytest.mark.parametrize(
    "field_name",
    ["anthropic_api_key", "modal_token_id", "modal_token_secret"],
)
def test_check_required_credentials_fails_fast_when_missing(monkeypatch, field_name):
    monkeypatch.setattr(settings, field_name, "")
    with pytest.raises(SystemExit) as exc_info:
        worker_mod._check_required_credentials()
    assert field_name.upper() in str(exc_info.value)


def test_build_worker_registers_both_workflows_and_all_activities(monkeypatch):
    captured = {}

    class FakeWorker:
        def __init__(self, client, **kwargs):
            captured["client"] = client
            captured.update(kwargs)

    monkeypatch.setattr(worker_mod, "Worker", FakeWorker)

    sentinel_client = object()
    worker_mod.build_worker(sentinel_client)

    assert captured["client"] is sentinel_client
    assert captured["task_queue"] == "document-analysis"

    workflow_names = {wf.__name__ for wf in captured["workflows"]}
    activity_names = {getattr(a, "__name__", None) for a in captured["activities"]}

    assert workflow_names == {"SubmissionWorkflow", "FileAnalysisWorkflow"}
    assert activity_names == {
        "mark_submission_running",
        "mark_submission_terminal",
        "mark_file_running",
        "mark_file_succeeded",
        "mark_file_failed",
        "provision_sandbox",
        "exec_tool",
        "terminate_sandbox",
        "call_claude",
    }
    assert captured["max_concurrent_activities"] == settings.worker_max_concurrent_activities
