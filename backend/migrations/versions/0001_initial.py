"""initial schema: tenants, submissions, files

Revision ID: 0001
Revises:
Create Date: 2026-08-29

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


submission_status = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "PARTIALLY_SUCCEEDED",
    "FAILED",
    name="submission_status",
    create_type=False,
)
file_status = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    name="file_status",
    create_type=False,
)
error_category = postgresql.ENUM(
    "VALIDATION",
    "SANDBOX",
    "LLM",
    "TOOL",
    "TIMEOUT",
    "INTERNAL",
    name="error_category",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    submission_status.create(bind, checkfirst=True)
    file_status.create(bind, checkfirst=True)
    error_category.create(bind, checkfirst=True)

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("status", submission_status, nullable=False, server_default="PENDING"),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("workflow_id", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_submissions_tenant_idempotency_key"
        ),
    )
    op.create_index(
        "ix_submissions_tenant_created", "submissions", ["tenant_id", sa.text("created_at DESC")]
    )

    op.create_table(
        "files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "submission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("status", file_status, nullable=False, server_default="PENDING"),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("error_category", error_category, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sandbox_id", sa.Text(), nullable=True),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_files_submission_id", "files", ["submission_id"])
    op.create_index("ix_files_tenant_status", "files", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_files_tenant_status", table_name="files")
    op.drop_index("ix_files_submission_id", table_name="files")
    op.drop_table("files")
    op.drop_index("ix_submissions_tenant_created", table_name="submissions")
    op.drop_table("submissions")
    op.drop_table("tenants")

    bind = op.get_bind()
    error_category.drop(bind, checkfirst=True)
    file_status.drop(bind, checkfirst=True)
    submission_status.drop(bind, checkfirst=True)
