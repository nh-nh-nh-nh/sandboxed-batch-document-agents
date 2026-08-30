"""Application configuration (SPEC.md §12).

pydantic-settings loads every value from the environment / `.env`, with
defaults matching `.env.example` exactly.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Postgres ---
    database_url: str = "postgresql+asyncpg://sbda:sbda@localhost:5432/sbda"

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        try:
            make_url(v)
        except Exception as e:
            raise ValueError(f"Malformed DATABASE_URL: {v!r} ({e})") from e
        return v

    # --- S3 / MinIO ---
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "sbda-documents"
    aws_access_key_id: str = "minioadmin"
    aws_secret_access_key: str = "minioadmin"
    aws_region: str = "us-east-1"

    # --- Temporal Cloud ---
    temporal_address: str = "sandboxed-batch-document-agents.ast5h.tmprl.cloud:7233"
    temporal_namespace: str = "sandboxed-batch-document-agents.ast5h"
    temporal_api_key: str = ""
    temporal_tls: bool = True
    temporal_task_queue: str = "document-analysis"
    worker_max_concurrent_activities: int = 16
    worker_max_concurrent_workflow_tasks: int = 100

    # --- Anthropic ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    anthropic_max_tokens: int = 8192
    anthropic_effort: str = "medium"

    # --- Modal ---
    modal_token_id: str = ""
    modal_token_secret: str = ""
    modal_app_name: str = "sandboxed-batch-document-agents"
    sandbox_timeout_s: int = 1200
    sandbox_cpu: float = 0.25
    sandbox_memory_mb: int = 1024
    tool_exec_timeout_s: int = 120

    # --- Limits ---
    max_files_per_submission: int = 100
    max_file_bytes: int = 1_048_576
    max_submission_bytes: int = 104_857_600
    tool_output_max_bytes: int = 32_768
    agent_max_turns: int = 25  # 0 = unlimited (see §9.5)

    # --- API ---
    upload_request_timeout_s: int = 600
    cors_origins: list[str] = ["http://localhost:5173"]

    def require_anthropic_credentials(self) -> None:
        if not self.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required but not set")

    def require_modal_credentials(self) -> None:
        if not self.modal_token_id:
            raise RuntimeError("MODAL_TOKEN_ID is required but not set")
        if not self.modal_token_secret:
            raise RuntimeError("MODAL_TOKEN_SECRET is required but not set")

    def require_temporal_credentials(self) -> None:
        if not self.temporal_api_key:
            raise RuntimeError("TEMPORAL_API_KEY is required but not set")


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
