"""Temporal worker entrypoint. See SPEC.md §6.2, §12.

Fails fast at startup if `ANTHROPIC_API_KEY` / `MODAL_TOKEN_*` are missing —
there is no point accepting work the process cannot possibly complete. Logs a
warning (does not fail) if Temporal server-side fairness looks disabled,
since fairness is a soft dependency (§6.1, §16.12): the system still works
correctly without it, it just degrades to FIFO dispatch.
"""

from __future__ import annotations

import asyncio
import logging
import sys

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
from sbda.temporal.activities.sandbox import exec_tool, provision_sandbox, terminate_sandbox
from sbda.temporal.shared import TASK_QUEUE
from sbda.temporal.workflows.file_analysis import FileAnalysisWorkflow
from sbda.temporal.workflows.submission import SubmissionWorkflow

logger = logging.getLogger("sbda.worker")

FAIRNESS_DOC_URL = (
    "https://docs.temporal.io — start the dev server with "
    "`--dynamic-config-value matching.enableFairness=true` "
    "(see infra/dynamicconfig/development.yaml for the compose path)"
)


def _check_required_credentials() -> None:
    missing = []
    if not settings.anthropic_api_key:
        missing.append("ANTHROPIC_API_KEY")
    if not settings.modal_token_id:
        missing.append("MODAL_TOKEN_ID")
    if not settings.modal_token_secret:
        missing.append("MODAL_TOKEN_SECRET")

    if missing:
        names = ", ".join(missing)
        raise SystemExit(
            f"sbda worker: missing required environment variable(s): {names}. "
            "Set them (see .env.example) before starting the worker."
        )


def _warn_about_fairness() -> None:
    """There is no client-side API to reliably read back the server's
    `matching.enableFairness` dynamic config flag, so this cannot be a real
    verification — it is a standing reminder every worker start, which is
    the point: fairness is a *soft* dependency (§6.1, §16.12). If it's not
    enabled server-side, everything still works, it just silently degrades
    to FIFO dispatch instead of per-tenant fair share, which would otherwise
    be an easy thing to lose track of.
    """
    logger.warning(
        "sbda worker: this worker assumes Temporal fairness "
        "(matching.enableFairness) is enabled on the server it connects to. "
        "If it is not, per-tenant dispatch fairness silently degrades to "
        "FIFO. %s",
        FAIRNESS_DOC_URL,
    )


def build_worker(client: Client) -> Worker:
    return Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[SubmissionWorkflow, FileAnalysisWorkflow],
        activities=[
            mark_submission_running,
            mark_submission_terminal,
            mark_file_running,
            mark_file_succeeded,
            mark_file_failed,
            provision_sandbox,
            exec_tool,
            terminate_sandbox,
            call_claude,
        ],
        max_concurrent_activities=settings.worker_max_concurrent_activities,
        max_concurrent_workflow_tasks=settings.worker_max_concurrent_workflow_tasks,
        max_concurrent_local_activities=settings.worker_max_concurrent_local_activities,
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    _check_required_credentials()

    client = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    _warn_about_fairness()

    worker = build_worker(client)
    logger.info(
        "sbda worker starting on task queue %r (max_concurrent_activities=%d)",
        TASK_QUEUE,
        settings.worker_max_concurrent_activities,
    )
    await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
