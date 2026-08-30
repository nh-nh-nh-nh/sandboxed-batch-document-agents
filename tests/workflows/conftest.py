"""Shared fixtures/fakes for `tests/workflows/` — Temporal time-skipping
environment with every activity mocked. SPEC.md §14.3.

Activities are dispatched by *name* (the Temporal activity type string), not
by Python object identity, so these fakes only need to share a name with the
real activities imported by workflow code (`mark_file_running`,
`provision_sandbox`, `call_claude`, ...) — they never touch a real database,
Modal, or Anthropic.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, field

import pytest_asyncio
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from sbda.temporal.activities.db import (
    MarkFileFailedInput,
    MarkFileRunningInput,
    MarkFileSucceededInput,
    MarkSubmissionRunningInput,
    MarkSubmissionTerminalInput,
)
from sbda.temporal.activities.llm import LLMInput, LLMResult
from sbda.temporal.activities.sandbox import (
    ExecToolInput,
    ExecToolResult,
    ProvisionInput,
    ProvisionResult,
    TerminateInput,
)
from sbda.temporal.shared import (
    TASK_QUEUE_ACTIVITIES,
    TASK_QUEUE_LLM,
    TASK_QUEUE_TERMINATE,
    TASK_QUEUE_WORKFLOW,
)
from sbda.temporal.workflows.file_analysis import FileAnalysisWorkflow
from sbda.temporal.workflows.submission import SubmissionWorkflow

# Activities routed to the "activities" queue in real workflow code
# (sbda/temporal/workflows/{submission,file_analysis}.py) — kept in sync by
# hand since there's no single source of truth to derive it from in tests.
_ACTIVITIES_QUEUE_NAMES = (
    "mark_submission_running",
    "mark_submission_terminal",
    "mark_file_running",
    "mark_file_succeeded",
    "mark_file_failed",
    "provision_sandbox",
    "exec_tool",
)


@dataclass
class FileRow:
    status: str = "PENDING"
    error_category: str | None = None
    error_message: str | None = None
    report: dict | None = None
    turn_count: int = 0
    attempt_count: int = 0


@dataclass
class Recorder:
    """Records every activity call and simulates the Postgres read model well
    enough for assertions (status transitions, terminate-call counts, etc.).
    """

    files: dict[str, FileRow] = field(default_factory=dict)
    submission_status: str | None = None
    submission_counts: tuple[int, int] | None = None
    terminate_calls: list[str] = field(default_factory=list)
    provision_calls: list[str] = field(default_factory=list)
    exec_calls: list[tuple] = field(default_factory=list)
    call_claude_calls: list[list[dict]] = field(default_factory=list)
    mark_file_running_calls: list[int] = field(default_factory=list)

    def file(self, file_id: str) -> FileRow:
        return self.files.setdefault(file_id, FileRow())


class Script:
    """Per-file scripted behavior for the sandbox + LLM activities, so each
    test can describe exactly what should happen without a real sandbox or
    a real model.

    `call_claude_turns`: list of (content, stop_reason) pairs, consumed in
    order across turns of the *whole run* (not reset across retries, callers
    that care about retries build a fresh Script per attempt via a factory).
    `provision_error`: an exception type to raise instead of succeeding.
    `provision_error_attempts`: if set, only raise on attempts <= this value
    (1-indexed); attempts after it succeed. None means "every attempt".
    `exec_tool_result`: fixed (content, is_error) returned for every
    sandbox tool call, unless `exec_tool_effect` is given.
    """

    def __init__(
        self,
        *,
        call_claude_turns=None,
        provision_error=None,
        provision_error_attempts=None,
        exec_tool_result=("<stdout>ok</stdout>\n<stderr></stderr>\nexit_code: 0", False),
        exec_tool_effect=None,
    ):
        self.call_claude_turns = list(call_claude_turns or [])
        self.provision_error = provision_error
        self.provision_error_attempts = provision_error_attempts
        self.exec_tool_result = exec_tool_result
        self.exec_tool_effect = exec_tool_effect


def build_fake_activities(recorder: Recorder, scripts: dict[str, Script]):
    """Returns the list of @activity.defn-decorated callables to register on
    the test Worker. `scripts` maps file_id -> Script.
    """

    def script_for(file_id: str) -> Script:
        return scripts.get(file_id, Script())

    @activity.defn(name="mark_submission_running")
    async def mark_submission_running(input: MarkSubmissionRunningInput) -> None:
        recorder.submission_status = "RUNNING"

    @activity.defn(name="mark_submission_terminal")
    async def mark_submission_terminal(input: MarkSubmissionTerminalInput) -> None:
        recorder.submission_status = input.status
        recorder.submission_counts = (input.succeeded_count, input.failed_count)
        for row in recorder.files.values():
            if row.status in ("PENDING", "RUNNING"):
                row.status = "FAILED"
                row.error_category = "INTERNAL"

    @activity.defn(name="mark_file_running")
    async def mark_file_running(input: MarkFileRunningInput) -> None:
        row = recorder.file(input.file_id)
        row.status = "RUNNING"
        row.attempt_count = input.attempt
        recorder.mark_file_running_calls.append(input.attempt)

    @activity.defn(name="mark_file_succeeded")
    async def mark_file_succeeded(input: MarkFileSucceededInput) -> None:
        row = recorder.file(input.file_id)
        row.status = "SUCCEEDED"
        row.report = input.report
        row.turn_count = input.turn_count

    @activity.defn(name="mark_file_failed")
    async def mark_file_failed(input: MarkFileFailedInput) -> None:
        row = recorder.file(input.file_id)
        row.status = "FAILED"
        row.error_category = input.error_category
        row.error_message = input.error_message

    @activity.defn(name="provision_sandbox")
    async def provision_sandbox(input: ProvisionInput) -> ProvisionResult:
        recorder.provision_calls.append(input.file_id)
        script = script_for(input.file_id)
        attempt = recorder.mark_file_running_calls[-1] if recorder.mark_file_running_calls else 1
        should_raise = script.provision_error is not None and (
            script.provision_error_attempts is None or attempt <= script.provision_error_attempts
        )
        if should_raise:
            raise script.provision_error(f"provision failed for {input.file_id}")
        return ProvisionResult(sandbox_id=f"sb-{input.file_id}")

    @activity.defn(name="exec_tool")
    async def exec_tool(input: ExecToolInput) -> ExecToolResult:
        recorder.exec_calls.append((input.sandbox_id, input.tool_name))
        script = script_for(input.sandbox_id.removeprefix("sb-"))
        if script.exec_tool_effect is not None:
            content, is_error = script.exec_tool_effect(input)
        else:
            content, is_error = script.exec_tool_result
        return ExecToolResult(content=content, is_error=is_error)

    @activity.defn(name="terminate_sandbox")
    async def terminate_sandbox(input: TerminateInput) -> None:
        recorder.terminate_calls.append(input.sandbox_id)

    @activity.defn(name="call_claude")
    async def call_claude(input: LLMInput) -> LLMResult:
        recorder.call_claude_calls.append(input.messages)

        if input.force_report:
            # Mirrors real Anthropic behavior with tool_choice pinned to
            # write_report (§9.5): the model literally cannot return anything
            # else on this turn, so the fake doesn't consult the script here.
            content = [
                {
                    "type": "tool_use",
                    "id": "forced_report",
                    "name": "write_report",
                    "input": {
                        "summary": "Cut short at the turn limit.",
                        "findings": [],
                    },
                }
            ]
            return LLMResult(
                content=content,
                stop_reason="tool_use",
                usage={"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0},
            )

        # Identify which file this call belongs to via the sandbox-free
        # initial user message text (it names the sanitized filename), so
        # multi-file workflow tests can script per-file turn sequences.
        file_key = _infer_file_key(input.messages)
        script = script_for(file_key)
        idx = sum(1 for m in recorder.call_claude_calls if _infer_file_key(m) == file_key) - 1
        if script.call_claude_turns:
            idx = min(idx, len(script.call_claude_turns) - 1)
            content, stop_reason = script.call_claude_turns[idx]
        else:
            content, stop_reason = (
                [{"type": "text", "text": "no script"}],
                "end_turn",
            )
        return LLMResult(
            content=content,
            stop_reason=stop_reason,
            usage={"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0},
        )

    return [
        mark_submission_running,
        mark_submission_terminal,
        mark_file_running,
        mark_file_succeeded,
        mark_file_failed,
        provision_sandbox,
        exec_tool,
        terminate_sandbox,
        call_claude,
    ]


@contextlib.asynccontextmanager
async def run_all_workers(client, recorder, scripts, *, llm_activities=None, skip_llm=False):
    """Starts one `Worker` per real task queue (workflow/activities/llm/
    terminate) — mirroring production's four-queue split (SPEC.md §6) — all
    backed by the same `Recorder`/`Script`-driven fakes from
    `build_fake_activities`. Individual workflow tests use this in place of a
    single combined `Worker`, since with activities routed to their own
    queues, one worker on the workflow queue alone would never see them.

    `llm_activities` overrides what's registered on the llm queue (e.g. to
    replace `call_claude` with one that raises, for error-path tests).
    `skip_llm` omits the llm worker entirely, e.g. to test schedule-to-start
    timeout behavior for an activity nothing ever picks up.
    """
    activities = {a.__name__: a for a in build_fake_activities(recorder, scripts)}
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(
            Worker(
                client,
                task_queue=TASK_QUEUE_WORKFLOW,
                workflows=[SubmissionWorkflow, FileAnalysisWorkflow],
            )
        )
        await stack.enter_async_context(
            Worker(
                client,
                task_queue=TASK_QUEUE_ACTIVITIES,
                activities=[activities[name] for name in _ACTIVITIES_QUEUE_NAMES],
            )
        )
        if not skip_llm:
            if llm_activities is None:
                llm_activities = [activities["call_claude"]]
            await stack.enter_async_context(
                Worker(client, task_queue=TASK_QUEUE_LLM, activities=llm_activities)
            )
        await stack.enter_async_context(
            Worker(
                client,
                task_queue=TASK_QUEUE_TERMINATE,
                activities=[activities["terminate_sandbox"]],
            )
        )
        yield


def _infer_file_key(messages: list[dict]) -> str:
    for m in messages:
        content = m.get("content")
        if isinstance(content, str) and "/work/input/" in content:
            # "...  /work/input/<sanitized_filename>\n\n..."
            after = content.split("/work/input/", 1)[1]
            return after.split("\n", 1)[0].strip()
    return "?"


@pytest_asyncio.fixture
async def temporal_env():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


def new_id() -> str:
    return str(uuid.uuid4())
