"""Real `TemporalClientInterface` implementation (see api/deps.py), wired in
by api/main.py's lifespan once a `temporalio.client.Client` is connected.
"""

from __future__ import annotations

import uuid

import temporalio.exceptions
from temporalio.client import Client

from sbda.api.deps import FileRef, WorkflowAlreadyStartedError
from sbda.temporal.shared import TASK_QUEUE, FileRef as WorkflowFileRef, SubmissionInput
from sbda.temporal.workflows.submission import SubmissionWorkflow


class RealTemporalClient:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def start_submission_workflow(
        self,
        *,
        submission_id: uuid.UUID,
        tenant_id: uuid.UUID,
        files: list[FileRef],
    ) -> None:
        try:
            await self._client.start_workflow(
                SubmissionWorkflow.run,
                SubmissionInput(
                    submission_id=str(submission_id),
                    tenant_id=str(tenant_id),
                    files=[
                        WorkflowFileRef(
                            file_id=str(f.file_id),
                            s3_key=f.s3_key,
                            original_filename=f.original_filename,
                            size_bytes=f.size_bytes,
                        )
                        for f in files
                    ],
                ),
                id=f"submission-{submission_id}",
                task_queue=TASK_QUEUE,
            )
        except temporalio.exceptions.WorkflowAlreadyStartedError as e:
            raise WorkflowAlreadyStartedError from e
