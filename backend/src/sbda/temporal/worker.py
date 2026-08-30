"""Temporal worker entrypoint. See SPEC.md §6.2, §12.

Four independent worker *roles* run as separate processes, each polling its
own task queue (`sbda.temporal.shared.TASK_QUEUE_*`):

- `workflow`   — SubmissionWorkflow / FileAnalysisWorkflow workflow tasks only,
                 no activities. GIL-bound (Python-SDK sandboxed replay runs on
                 a thread pool), so its concurrency knobs are tuned separately
                 from activity throughput.
- `activities` — provision_sandbox, exec_tool, and the mark_* DB activities.
- `llm`        — call_claude, so its concurrency can be tuned to the Anthropic
                 rate limit independently of Modal capacity.
- `terminate`  — terminate_sandbox only, on its own small dedicated pool, so a
                 Modal capacity crunch that stalls provision_sandbox can never
                 starve the one activity that would relieve it.

Run with `python -m sbda.temporal.worker <role>`.

Fails fast at startup if the credentials that role's activities need are
missing — there is no point accepting work the process cannot possibly
complete. Logs a warning (does not fail) if Temporal Cloud namespace-level
fairness looks disabled, since fairness is a soft dependency (§6.1, §16.12):
the system still works correctly without it, it just degrades to FIFO
dispatch.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from sbda.config import settings
from sbda.temporal.activities.db import (
    mark_file_failed,
    mark_file_running,
    mark_file_succeeded,
    mark_submission_running,
    mark_submission_terminal,
)
from sbda.temporal.activities.llm import call_claude
from sbda.temporal.activities.sandbox import (
    exec_tool,
    provision_sandbox,
    recover_sandbox,
    terminate_sandbox,
)
from sbda.temporal.shared import (
    TASK_QUEUE_ACTIVITIES,
    TASK_QUEUE_LLM,
    TASK_QUEUE_TERMINATE,
    TASK_QUEUE_WORKFLOW,
)
from sbda.temporal.workflows.file_analysis import FileAnalysisWorkflow
from sbda.temporal.workflows.submission import SubmissionWorkflow

logger = logging.getLogger("sbda.worker")

FAIRNESS_DOC_URL = (
    "https://cloud.temporal.io — enable it under the namespace's "
    "Settings -> Fairness panel (this is a per-namespace toggle in the "
    "Temporal Cloud console, not a CLI flag or dynamic-config file)"
)

# Credentials each role's activities actually need, beyond TEMPORAL_API_KEY
# (required for every role — the worker can't connect at all without it).
_ROLE_REQUIRED_SETTINGS: dict[str, list[str]] = {
    "workflow": [],
    "activities": ["modal_token_id", "modal_token_secret"],
    "llm": ["anthropic_api_key"],
    "terminate": ["modal_token_id", "modal_token_secret"],
}


def _check_required_credentials(role: str) -> None:
    missing = []
    if not settings.temporal_api_key:
        missing.append("TEMPORAL_API_KEY")
    for field_name in _ROLE_REQUIRED_SETTINGS[role]:
        if not getattr(settings, field_name):
            missing.append(field_name.upper())

    if missing:
        names = ", ".join(missing)
        raise SystemExit(
            f"sbda worker ({role}): missing required environment variable(s): {names}. "
            "Set them (see .env.example) before starting the worker."
        )


def _warn_about_fairness() -> None:
    """There is no client-side API to reliably read back the namespace's
    Fairness toggle, so this cannot be a real verification — it is a standing
    reminder every worker start, which is the point: fairness is a *soft*
    dependency (§6.1, §16.12). If it's not enabled in the Temporal Cloud
    console, everything still works, it just silently degrades to FIFO
    dispatch instead of per-tenant fair share, which would otherwise be an
    easy thing to lose track of.
    """
    logger.warning(
        "sbda worker: this worker assumes Fairness is enabled on namespace "
        "%r in the Temporal Cloud console. If it is not, per-tenant "
        "dispatch fairness silently degrades to FIFO. %s",
        settings.temporal_namespace,
        FAIRNESS_DOC_URL,
    )


def build_workflow_worker(client: Client) -> Worker:
    return Worker(
        client,
        task_queue=TASK_QUEUE_WORKFLOW,
        workflows=[SubmissionWorkflow, FileAnalysisWorkflow],
        max_concurrent_workflow_tasks=settings.worker_max_concurrent_workflow_tasks,
        workflow_task_executor=ThreadPoolExecutor(
            max_workers=settings.worker_workflow_task_executor_threads
        ),
    )


def build_activities_worker(client: Client) -> Worker:
    return Worker(
        client,
        task_queue=TASK_QUEUE_ACTIVITIES,
        activities=[
            mark_submission_running,
            mark_submission_terminal,
            mark_file_running,
            mark_file_succeeded,
            mark_file_failed,
            provision_sandbox,
            exec_tool,
            recover_sandbox,
        ],
        max_concurrent_activities=settings.worker_max_concurrent_activities,
    )


def build_llm_worker(client: Client) -> Worker:
    return Worker(
        client,
        task_queue=TASK_QUEUE_LLM,
        activities=[call_claude],
        max_concurrent_activities=settings.worker_max_concurrent_llm_activities,
    )


def build_terminate_worker(client: Client) -> Worker:
    return Worker(
        client,
        task_queue=TASK_QUEUE_TERMINATE,
        activities=[terminate_sandbox],
        max_concurrent_activities=settings.worker_max_concurrent_terminate_activities,
    )


ROLE_BUILDERS = {
    "workflow": build_workflow_worker,
    "activities": build_activities_worker,
    "llm": build_llm_worker,
    "terminate": build_terminate_worker,
}


async def main(role: str) -> None:
    logging.basicConfig(level=logging.INFO)
    _check_required_credentials(role)

    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        tls=settings.temporal_tls,
        api_key=settings.temporal_api_key,
    )
    _warn_about_fairness()

    worker = ROLE_BUILDERS[role](client)
    logger.info("sbda worker (%s) starting on task queue %r", role, worker.task_queue)
    await worker.run()


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ROLE_BUILDERS:
            valid = ", ".join(sorted(ROLE_BUILDERS))
            raise SystemExit(
                f"usage: python -m sbda.temporal.worker <role>, where <role> is one of: {valid}"
            )
        asyncio.run(main(sys.argv[1]))
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
