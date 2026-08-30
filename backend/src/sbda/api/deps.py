"""FastAPI dependencies: db session, tenant resolution, S3 client, and the
Temporal client interface.

The real Temporal client lives in another slice (SubmissionWorkflow /
FileAnalysisWorkflow). `TemporalClientInterface` defines the exact shape this
API needs; `StubTemporalClient` is a placeholder that logs instead of
starting a real workflow. Wiring the real client in is a one-line change:
construct it in `lifespan` (api/main.py) and pass it to
`set_temporal_client`, or override `get_temporal_client` as a FastAPI
dependency.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sbda.config import Settings
from sbda.config import settings as default_settings
from sbda.db.engine import get_sessionmaker
from sbda.db.models import Tenant
from sbda.storage.s3 import S3Client

logger = logging.getLogger(__name__)


def get_settings() -> Settings:
    return default_settings


async def get_db(
    settings: Settings = Depends(get_settings),
) -> AsyncIterator[AsyncSession]:
    session_factory = get_sessionmaker(settings.database_url)
    async with session_factory() as session:
        yield session


def get_s3_client(settings: Settings = Depends(get_settings)) -> S3Client:
    return S3Client.from_settings(settings)


async def resolve_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


# --- Temporal client interface (stub — the real implementation lives in the
# Temporal-workflow slice) ---------------------------------------------------


@dataclass(frozen=True)
class FileRef:
    file_id: uuid.UUID
    s3_key: str
    original_filename: str
    size_bytes: int


class WorkflowAlreadyStartedError(Exception):
    """Raised by a TemporalClientInterface implementation when the
    deterministic workflow id already has a running execution. The caller
    (routes_submissions.py, §5.2 step 5) swallows this and treats it as
    success."""


class TemporalClientInterface(Protocol):
    async def start_submission_workflow(
        self,
        *,
        submission_id: uuid.UUID,
        tenant_id: uuid.UUID,
        files: list[FileRef],
    ) -> None:
        """Start `submission-{submission_id}` (SubmissionWorkflow.run) with a
        deterministic workflow id, per SPEC.md §7.1. Must raise
        `WorkflowAlreadyStartedError` (not the raw Temporal exception) when
        that id is already running."""
        ...


class StubTemporalClient:
    """No-op placeholder satisfying `TemporalClientInterface`, until the
    Temporal-workflow slice wires this to a real `temporalio.client.Client`
    and `start_workflow(SubmissionWorkflow.run, ...)`."""

    async def start_submission_workflow(
        self,
        *,
        submission_id: uuid.UUID,
        tenant_id: uuid.UUID,
        files: list[FileRef],
    ) -> None:
        logger.info(
            "StubTemporalClient: would start submission-%s for tenant %s with %d file(s)",
            submission_id,
            tenant_id,
            len(files),
        )


_temporal_client: TemporalClientInterface = StubTemporalClient()


def set_temporal_client(client: TemporalClientInterface) -> None:
    """Swap the process-wide Temporal client. Call this once at startup
    (api/main.py lifespan) once the real client is available."""

    global _temporal_client
    _temporal_client = client


def get_temporal_client() -> TemporalClientInterface:
    return _temporal_client
