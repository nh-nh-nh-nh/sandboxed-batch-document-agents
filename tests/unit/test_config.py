from __future__ import annotations

import pytest
from pydantic import ValidationError

from sbda.config import Settings


def _settings(**overrides) -> Settings:
    # Bypass any local .env so defaults are what's actually asserted.
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_agent_max_turns_defaults_to_25():
    assert _settings().agent_max_turns == 25


def test_agent_max_turns_zero_means_unlimited():
    s = _settings(agent_max_turns=0)
    assert s.agent_max_turns == 0


def test_agent_max_turns_positive_means_capped():
    s = _settings(agent_max_turns=10)
    assert s.agent_max_turns > 0


def test_defaults_match_env_example():
    s = _settings()
    assert s.database_url == "postgresql+asyncpg://sbda:sbda@localhost:5432/sbda"
    assert s.s3_endpoint_url == "http://localhost:9000"
    assert s.s3_bucket == "sbda-documents"
    assert s.aws_access_key_id == "minioadmin"
    assert s.aws_secret_access_key == "minioadmin"
    assert s.aws_region == "us-east-1"
    assert s.temporal_address == "localhost:7233"
    assert s.temporal_namespace == "default"
    assert s.temporal_task_queue == "document-analysis"
    assert s.worker_max_concurrent_activities == 16
    assert s.worker_max_concurrent_workflow_tasks == 100
    assert s.anthropic_model == "claude-sonnet-5"
    assert s.anthropic_max_tokens == 8192
    assert s.anthropic_effort == "medium"
    assert s.modal_app_name == "sbda-sandboxes"
    assert s.sandbox_timeout_s == 1200
    assert s.sandbox_cpu == 0.25
    assert s.sandbox_memory_mb == 1024
    assert s.tool_exec_timeout_s == 120
    assert s.max_files_per_submission == 100
    assert s.max_file_bytes == 1_048_576
    assert s.max_submission_bytes == 104_857_600
    assert s.tool_output_max_bytes == 32_768


def test_missing_anthropic_api_key_raises_at_worker_startup():
    s = _settings(anthropic_api_key="")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        s.require_anthropic_credentials()


def test_missing_modal_token_raises_naming_variable():
    s = _settings(modal_token_id="", modal_token_secret="")
    with pytest.raises(RuntimeError, match="MODAL_TOKEN_ID"):
        s.require_modal_credentials()


def test_byte_size_vars_parse_as_integers():
    s = _settings(max_file_bytes="2048", max_submission_bytes="4096")
    assert s.max_file_bytes == 2048
    assert isinstance(s.max_file_bytes, int)
    assert s.max_submission_bytes == 4096


def test_malformed_database_url_fails_fast():
    with pytest.raises(ValidationError):
        _settings(database_url="not-a-valid-url ::: nope")
