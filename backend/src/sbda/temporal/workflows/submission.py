"""`SubmissionWorkflow` — the parent workflow that fans out one child
`FileAnalysisWorkflow` per file and fans results back in. See SPEC.md §7.1.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from sbda.core.rollup import rollup
    from sbda.temporal.activities.db import (
        MarkSubmissionRunningInput,
        MarkSubmissionTerminalInput,
        mark_submission_running,
        mark_submission_terminal,
    )
    from sbda.temporal.shared import (
        CHILD_WORKFLOW_RETRY_POLICY,
        FILE_WORKFLOW_RUN_TIMEOUT,
        MARK_DB_RETRY_POLICY,
        FileInput,
        SubmissionInput,
        SubmissionResult,
        fairness_priority,
    )

# Imported normally (not passed through): this is another workflow definition
# in our own codebase, meant to run inside the sandbox like any workflow.
from sbda.temporal.workflows.file_analysis import FileAnalysisWorkflow


@workflow.defn
class SubmissionWorkflow:
    @workflow.run
    async def run(self, input: SubmissionInput) -> SubmissionResult:
        priority = fairness_priority(input.tenant_id)

        await workflow.execute_activity(
            mark_submission_running,
            MarkSubmissionRunningInput(submission_id=input.submission_id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=MARK_DB_RETRY_POLICY,
            priority=priority,
        )

        handles = [
            workflow.execute_child_workflow(
                FileAnalysisWorkflow.run,
                FileInput(
                    file_id=f.file_id,
                    submission_id=input.submission_id,
                    tenant_id=input.tenant_id,
                    s3_key=f.s3_key,
                    original_filename=f.original_filename,
                    size_bytes=f.size_bytes,
                    # The S3 key's basename *is* the sanitized filename the
                    # uploader already computed and stored the object under
                    # (§4.1); reuse it verbatim rather than recompute, so the
                    # sandbox path always matches what's actually in S3.
                    sanitized_filename=f.s3_key.rsplit("/", 1)[-1],
                ),
                id=f"file-{f.file_id}",
                priority=priority,
                retry_policy=CHILD_WORKFLOW_RETRY_POLICY,
                run_timeout=FILE_WORKFLOW_RUN_TIMEOUT,
                # parent_close_policy intentionally left at its default
                # (TERMINATE) — ABANDON is NOT used (§7.1).
            )
            for f in input.files
        ]

        results = await asyncio.gather(*handles, return_exceptions=True)
        # `return_exceptions=True` is essential: the parent never cancels
        # siblings when one child fails. A failed file is data, not a
        # control-flow event — every child runs to completion.

        statuses = [
            r.status if not isinstance(r, BaseException) else r for r in results
        ]
        result = rollup(statuses)

        await workflow.execute_activity(
            mark_submission_terminal,
            MarkSubmissionTerminalInput(
                submission_id=input.submission_id,
                status=result.status.value,
                succeeded_count=result.succeeded,
                failed_count=result.failed,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=MARK_DB_RETRY_POLICY,
            priority=priority,
        )

        return SubmissionResult(
            status=result.status.value, succeeded=result.succeeded, failed=result.failed
        )
