"""Real `TemporalClientInterface` implementation (see api/deps.py), wired in
by api/main.py's lifespan once a `temporalio.client.Client` is connected.
"""

from __future__ import annotations

import uuid

import temporalio.exceptions
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from sbda.api.deps import FileRef, WorkflowAlreadyStartedError
from sbda.temporal.shared import TASK_QUEUE_WORKFLOW, SubmissionInput
from sbda.temporal.shared import FileRef as WorkflowFileRef
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
    ) -> str | None:
        try:
            handle = await self._client.start_workflow(
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
                task_queue=TASK_QUEUE_WORKFLOW,
                # A submission id must run at most once, ever — not just
                # "not currently running". Rejecting any duplicate (even one
                # whose earlier execution already completed) is what makes
                # it safe for the API layer to retry a start it isn't sure
                # succeeded (see routes_submissions.py::_ensure_workflow_started).
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except temporalio.exceptions.WorkflowAlreadyStartedError as e:
            raise WorkflowAlreadyStartedError from e
        return handle.first_execution_run_id
