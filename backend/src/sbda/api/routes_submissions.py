"""Submission endpoints (SPEC.md §5.2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Response, UploadFile
from fastapi import File as UploadFileField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sbda.api.deps import (
    FileRef,
    TemporalClientInterface,
    WorkflowAlreadyStartedError,
    get_db,
    get_s3_client,
    get_settings,
    get_temporal_client,
    resolve_tenant,
)
from sbda.config import Settings
from sbda.core.enums import FileStatus, SubmissionStatus
from sbda.core.validation import (
    NoFilesError,
    TooManyFilesError,
    UnsupportedExtensionError,
    validate_extension,
)
from sbda.db.models import File as FileRow
from sbda.db.models import Submission, Tenant
from sbda.storage.s3 import S3Client, UploadTooLargeError

router = APIRouter(prefix="/api/tenants/{tenant_id}", tags=["submissions"])


def _enum_value(v):
    return v.value if hasattr(v, "value") else v


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def _file_payload(f: FileRow) -> dict:
    return {
        "id": str(f.id),
        "submission_id": str(f.submission_id),
        "original_filename": f.original_filename,
        "size_bytes": f.size_bytes,
        "content_type": f.content_type,
        "status": _enum_value(f.status),
        "has_report": f.report is not None,
        "error_category": _enum_value(f.error_category) if f.error_category else None,
        "error_message": f.error_message,
        "attempt_count": f.attempt_count,
        "sandbox_id": f.sandbox_id,
        "turn_count": f.turn_count,
        "input_tokens": f.input_tokens,
        "output_tokens": f.output_tokens,
        "cache_read_tokens": f.cache_read_tokens,
        "started_at": _iso(f.started_at),
        "finished_at": _iso(f.finished_at),
        "created_at": _iso(f.created_at),
        "updated_at": _iso(f.updated_at),
    }


def _submission_summary_payload(s: Submission) -> dict:
    return {
        "id": str(s.id),
        "tenant_id": str(s.tenant_id),
        "status": _enum_value(s.status),
        "file_count": s.file_count,
        "succeeded_count": s.succeeded_count,
        "failed_count": s.failed_count,
        "idempotency_key": s.idempotency_key,
        "workflow_id": s.workflow_id,
        "run_id": s.run_id,
        "error_message": s.error_message,
        "created_at": _iso(s.created_at),
        "updated_at": _iso(s.updated_at),
    }


async def _submission_detail_payload(db: AsyncSession, submission: Submission) -> dict:
    result = await db.execute(
        select(FileRow)
        .where(FileRow.submission_id == submission.id)
        .order_by(FileRow.created_at)
    )
    files = result.scalars().all()
    payload = _submission_summary_payload(submission)
    payload["files"] = [_file_payload(f) for f in files]
    return payload


@router.post("/submissions", status_code=202)
async def create_submission(
    tenant_id: uuid.UUID,
    response: Response,
    files: list[UploadFile] | None = UploadFileField(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
    s3: S3Client = Depends(get_s3_client),
    temporal: TemporalClientInterface = Depends(get_temporal_client),
    settings: Settings = Depends(get_settings),
) -> dict:
    # 1. Idempotency check — no new upload, no new workflow.
    if idempotency_key:
        result = await db.execute(
            select(Submission).where(
                Submission.tenant_id == tenant.id,
                Submission.idempotency_key == idempotency_key,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            response.status_code = 200
            return await _submission_detail_payload(db, existing)

    # 2. Batch validation, before reading any file body.
    files = files or []
    if len(files) == 0:
        raise HTTPException(
            status_code=400, detail={"error": "NO_FILES", "message": str(NoFilesError())}
        )
    if len(files) > settings.max_files_per_submission:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "TOO_MANY_FILES",
                "message": str(TooManyFilesError(len(files), settings.max_files_per_submission)),
            },
        )
    for f in files:
        try:
            validate_extension(f.filename or "")
        except UnsupportedExtensionError as e:
            raise HTTPException(
                status_code=400, detail={"error": "UNSUPPORTED_EXTENSION", "message": str(e)}
            ) from e

    # 3. Per-file streaming upload, with per-file and per-submission caps
    #    enforced during the stream.
    submission_id = uuid.uuid4()
    uploaded_keys: list[str] = []
    file_rows: list[dict] = []
    total_bytes = 0

    for f in files:
        file_id = uuid.uuid4()
        key = s3.build_key(str(tenant.id), str(submission_id), str(file_id), f.filename or "")
        try:
            size = s3.upload_fileobj_capped(
                f.file, key, max_bytes=settings.max_file_bytes, content_type=f.content_type
            )
        except UploadTooLargeError as e:
            s3.delete_objects(uploaded_keys)
            raise HTTPException(
                status_code=413,
                detail={
                    "error": "FILE_TOO_LARGE",
                    "message": f"{f.filename!r} exceeds the per-file cap of "
                    f"{settings.max_file_bytes} bytes",
                },
            ) from e

        uploaded_keys.append(key)
        total_bytes += size

        if total_bytes > settings.max_submission_bytes:
            s3.delete_objects(uploaded_keys)
            raise HTTPException(
                status_code=413,
                detail={
                    "error": "SUBMISSION_TOO_LARGE",
                    "message": f"Submission exceeds the cap of "
                    f"{settings.max_submission_bytes} bytes",
                },
            )

        file_rows.append(
            {
                "id": file_id,
                "s3_key": key,
                "original_filename": f.filename or "",
                "size_bytes": size,
                "content_type": f.content_type,
            }
        )

    # 4. One transaction inserts the submission + all file rows.
    try:
        submission = Submission(
            id=submission_id,
            tenant_id=tenant.id,
            status=SubmissionStatus.PENDING,
            file_count=len(file_rows),
            idempotency_key=idempotency_key,
            workflow_id=f"submission-{submission_id}",
        )
        db.add(submission)
        for row in file_rows:
            db.add(
                FileRow(
                    id=row["id"],
                    submission_id=submission_id,
                    tenant_id=tenant.id,
                    original_filename=row["original_filename"],
                    s3_key=row["s3_key"],
                    size_bytes=row["size_bytes"],
                    content_type=row["content_type"],
                    status=FileStatus.PENDING,
                )
            )
        await db.commit()
    except Exception:
        await db.rollback()
        s3.delete_objects(uploaded_keys)
        raise

    # 5. Start the workflow. A deterministic id means WorkflowAlreadyStartedError
    #    is success, not failure.
    refs = [
        FileRef(
            file_id=row["id"],
            s3_key=row["s3_key"],
            original_filename=row["original_filename"],
            size_bytes=row["size_bytes"],
        )
        for row in file_rows
    ]
    try:
        await temporal.start_submission_workflow(
            submission_id=submission_id, tenant_id=tenant.id, files=refs
        )
    except WorkflowAlreadyStartedError:
        pass

    await db.refresh(submission)
    response.status_code = 202
    return await _submission_detail_payload(db, submission)


@router.get("/submissions/{submission_id}")
async def get_submission(
    tenant_id: uuid.UUID,
    submission_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Submission).where(
            Submission.id == submission_id, Submission.tenant_id == tenant.id
        )
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    return await _submission_detail_payload(db, submission)


@router.get("/submissions")
async def list_submissions(
    tenant_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(Submission)
        .where(Submission.tenant_id == tenant.id)
        .order_by(Submission.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_submission_summary_payload(s) for s in result.scalars().all()]


@router.get("/files/{file_id}/report")
async def get_file_report(
    tenant_id: uuid.UUID,
    file_id: uuid.UUID,
    tenant: Tenant = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(FileRow).where(FileRow.id == file_id, FileRow.tenant_id == tenant.id)
    )
    f = result.scalar_one_or_none()
    if f is None or f.report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return f.report
