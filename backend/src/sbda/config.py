# STUB — owned by the backend-foundation slice (see SPEC.md §12, §2).
#
# This is a minimal implementation of `sbda.config.settings` sufficient for the
# temporal/agent/sandbox slice (workflows, activities, agent runtime, and their
# tests) to import `from sbda.config import settings` and get the fields it
# needs, with defaults matching SPEC.md §12 exactly. Reconcile against the
# backend-foundation PR's real `config.py` — in particular, that PR may add a
# real pydantic-settings `BaseSettings` subclass with additional validation
# (e.g. "missing ANTHROPIC_API_KEY raises at import/startup", "malformed
# DATABASE_URL fails fast") described in SPEC.md §14.1 `test_config.py`, which
# this stub does not fully implement.

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Postgres ---
    database_url: str = "postgresql+asyncpg://sbda:sbda@localhost:5432/sbda"

    # --- S3 / MinIO ---
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "sbda-documents"
    aws_access_key_id: str = "minioadmin"
    aws_secret_access_key: str = "minioadmin"
    aws_region: str = "us-east-1"

    # --- Temporal ---
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "document-analysis"
    worker_max_concurrent_activities: int = 16
    worker_max_concurrent_workflow_tasks: int = 100
    worker_max_concurrent_local_activities: int = 16

    # --- Anthropic ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    anthropic_max_tokens: int = 8192
    anthropic_effort: str = "medium"

    # --- Modal ---
    modal_token_id: str = ""
    modal_token_secret: str = ""
    modal_app_name: str = "sbda-sandboxes"
    sandbox_timeout_s: int = 1200
    sandbox_cpu: float = 0.25
    sandbox_memory_mb: int = 1024
    tool_exec_timeout_s: int = 120

    # --- Limits ---
    max_files_per_submission: int = 100
    max_file_bytes: int = 1_048_576
    max_submission_bytes: int = 104_857_600
    tool_output_max_bytes: int = 32_768
    agent_max_turns: int = 25  # 0 = unlimited


settings = Settings()
