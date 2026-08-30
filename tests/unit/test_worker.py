"""Smoke tests for `sbda.temporal.worker` — the fail-fast credential check per
role and the workflow/activity/queue wiring for each of the four worker
roles. No real Temporal connection is made.
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
    monkeypatch.setattr(settings, "temporal_api_key", "temporal-key")


@pytest.fixture
def fake_worker(monkeypatch):
    captured = {}

    class FakeWorker:
        def __init__(self, client, **kwargs):
            captured["client"] = client
            captured.update(kwargs)

    monkeypatch.setattr(worker_mod, "Worker", FakeWorker)
    return captured


@pytest.mark.parametrize("role", ["workflow", "activities", "llm", "terminate"])
def test_check_required_credentials_passes_when_all_present(role):
    worker_mod._check_required_credentials(role)  # must not raise


def test_workflow_role_does_not_require_modal_or_anthropic_credentials(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "modal_token_id", "")
    monkeypatch.setattr(settings, "modal_token_secret", "")
    worker_mod._check_required_credentials("workflow")  # must not raise


@pytest.mark.parametrize("role", ["workflow", "activities", "llm", "terminate"])
def test_check_required_credentials_fails_fast_when_temporal_key_missing(monkeypatch, role):
    monkeypatch.setattr(settings, "temporal_api_key", "")
    with pytest.raises(SystemExit) as exc_info:
        worker_mod._check_required_credentials(role)
    assert "TEMPORAL_API_KEY" in str(exc_info.value)


@pytest.mark.parametrize(
    "role,field_name",
    [
        ("activities", "modal_token_id"),
        ("activities", "modal_token_secret"),
        ("terminate", "modal_token_id"),
        ("terminate", "modal_token_secret"),
        ("llm", "anthropic_api_key"),
    ],
)
def test_check_required_credentials_fails_fast_for_role_specific_creds(
    monkeypatch, role, field_name
):
    monkeypatch.setattr(settings, field_name, "")
    with pytest.raises(SystemExit) as exc_info:
        worker_mod._check_required_credentials(role)
    assert field_name.upper() in str(exc_info.value)


def test_build_workflow_worker(fake_worker):
    sentinel_client = object()
    worker_mod.build_workflow_worker(sentinel_client)

    assert fake_worker["client"] is sentinel_client
    assert fake_worker["task_queue"] == "document-analysis-workflow"
    assert {wf.__name__ for wf in fake_worker["workflows"]} == {
        "SubmissionWorkflow",
        "FileAnalysisWorkflow",
    }
    expected_tasks = settings.worker_max_concurrent_workflow_tasks
    assert fake_worker["max_concurrent_workflow_tasks"] == expected_tasks
    expected_threads = settings.worker_workflow_task_executor_threads
    assert fake_worker["workflow_task_executor"]._max_workers == expected_threads


def test_build_activities_worker(fake_worker):
    sentinel_client = object()
    worker_mod.build_activities_worker(sentinel_client)

    assert fake_worker["client"] is sentinel_client
    assert fake_worker["task_queue"] == "document-analysis-activities"
    activity_names = {getattr(a, "__name__", None) for a in fake_worker["activities"]}
    assert activity_names == {
        "mark_submission_running",
        "mark_submission_terminal",
        "mark_file_running",
        "mark_file_succeeded",
        "mark_file_failed",
        "provision_sandbox",
        "exec_tool",
        "recover_sandbox",
    }
    assert fake_worker["max_concurrent_activities"] == settings.worker_max_concurrent_activities


def test_build_llm_worker(fake_worker):
    sentinel_client = object()
    worker_mod.build_llm_worker(sentinel_client)

    assert fake_worker["client"] is sentinel_client
    assert fake_worker["task_queue"] == "document-analysis-llm"
    activity_names = {getattr(a, "__name__", None) for a in fake_worker["activities"]}
    assert activity_names == {"call_claude"}
    assert fake_worker["max_concurrent_activities"] == settings.worker_max_concurrent_llm_activities


def test_build_terminate_worker(fake_worker):
    sentinel_client = object()
    worker_mod.build_terminate_worker(sentinel_client)

    assert fake_worker["client"] is sentinel_client
    assert fake_worker["task_queue"] == "document-analysis-terminate"
    activity_names = {getattr(a, "__name__", None) for a in fake_worker["activities"]}
    assert activity_names == {"terminate_sandbox"}
    expected = settings.worker_max_concurrent_terminate_activities
    assert fake_worker["max_concurrent_activities"] == expected


def test_role_builders_cover_exactly_the_four_roles():
    assert set(worker_mod.ROLE_BUILDERS) == {"workflow", "activities", "llm", "terminate"}
