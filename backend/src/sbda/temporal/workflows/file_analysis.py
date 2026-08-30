"""`FileAnalysisWorkflow` — the child workflow that runs the agentic loop for
one file. See SPEC.md §7.2 for the exact numbered pseudocode this follows and
§7.3 for the determinism notes.

Determinism (§7.3): no `datetime.now()`, `random`, `uuid4`, or I/O in this
module. Every id comes from `FileInput`; every timestamp is written by an
activity (`func.now()` in SQL, never workflow-observed wall-clock). `messages`
accumulates in workflow state and is replayed from history — that is what
makes the loop durable, and also what the turn cap (§9.5) exists to bound.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from sbda.agent.messages import (
        UsageTotals,
        accumulate_usage,
        build_tool_result_block,
        build_tool_results_message,
    )
    from sbda.agent.prompts import TURN_LIMIT_MESSAGE, build_initial_user_message
    from sbda.config import settings
    from sbda.core.errors import (
        LLMClientError,
        LLMConnectionError,
        LLMRateLimitError,
        LLMServerError,
        SandboxGoneError,
        ValidationError,
        classify,
    )
    from sbda.core.report import ReportValidationError, validate_report
    from sbda.db.models import ErrorCategory, FileStatus
    from sbda.temporal.activities.db import (
        MarkFileFailedInput,
        MarkFileRunningInput,
        MarkFileSucceededInput,
        mark_file_failed,
        mark_file_running,
        mark_file_succeeded,
    )
    from sbda.temporal.activities.llm import LLMInput, call_claude
    from sbda.temporal.activities.sandbox import (
        ExecToolInput,
        ProvisionInput,
        RecoverSandboxInput,
        TerminateInput,
        exec_tool,
        provision_sandbox,
        recover_sandbox,
        terminate_sandbox,
    )
    from sbda.temporal.shared import (
        CALL_CLAUDE_RETRY_POLICY,
        CALL_CLAUDE_SCHEDULE_TO_START_TIMEOUT,
        CALL_CLAUDE_START_TO_CLOSE_TIMEOUT,
        EXEC_TOOL_RETRY_POLICY,
        EXEC_TOOL_START_TO_CLOSE_TIMEOUT,
        MARK_DB_RETRY_POLICY,
        PROVISION_SANDBOX_RETRY_POLICY,
        PROVISION_SANDBOX_START_TO_CLOSE_TIMEOUT,
        RECOVER_SANDBOX_RETRY_POLICY,
        RECOVER_SANDBOX_START_TO_CLOSE_TIMEOUT,
        TASK_QUEUE_ACTIVITIES,
        TASK_QUEUE_LLM,
        TASK_QUEUE_TERMINATE,
        TERMINATE_SANDBOX_RETRY_POLICY,
        TERMINATE_SANDBOX_START_TO_CLOSE_TIMEOUT,
        FileInput,
        FileResult,
        fairness_priority,
    )


_KNOWN_EXCEPTION_TYPES = {
    "ValidationError": ValidationError,
    "LLMClientError": LLMClientError,
    "SandboxGoneError": SandboxGoneError,
    "RateLimitError": LLMRateLimitError,
    "APIStatusError": LLMServerError,
    "APIConnectionError": LLMConnectionError,
}


def _root_cause(exc: BaseException) -> BaseException:
    """Walk Temporal's `ActivityError -> ... -> ApplicationError` cause chain
    down to the innermost failure, since that's where the original exception's
    type name (and, for our own exceptions, its message) actually lives once
    it has crossed the activity/workflow boundary.
    """
    seen: set[int] = set()
    current = exc
    while getattr(current, "cause", None) is not None and id(current) not in seen:
        seen.add(id(current))
        current = current.cause
    return current


def _any_non_retryable(exc: BaseException) -> bool:
    """Whether any exception in the `cause` chain was explicitly marked
    `non_retryable=True`. Unlike `_root_cause`, this must inspect every link,
    not just the innermost one: `raise ApplicationError(..., non_retryable=True)
    from e` round-trips across the activity/workflow boundary as an outer
    ApplicationError (carrying the flag) wrapping an inner, auto-wrapped
    ApplicationError for `e` itself (which never carries it) — so checking
    only `_root_cause(exc)` would always see `non_retryable=False`.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if getattr(current, "non_retryable", False):
            return True
        seen.add(id(current))
        current = getattr(current, "cause", None)
    return False


def _first_known_type_name(exc: BaseException) -> str | None:
    """Scan the *whole* cause chain (outer to inner) for a type name present
    in `_KNOWN_EXCEPTION_TYPES`. `raise SandboxGoneError(...) from e` always
    chains to the underlying SDK exception (e.g. `NotFoundError`), so the
    *outer* link carries our own exception's name while the innermost link
    carries the SDK's — `_root_cause()` alone would find the SDK's name, not
    ours, and silently misclassify every real chained sandbox failure.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        type_name = getattr(current, "type", None) or type(current).__name__
        if type_name in _KNOWN_EXCEPTION_TYPES:
            return type_name
        seen.add(id(current))
        current = getattr(current, "cause", None)
    return None


def _is_sandbox_gone(exc: BaseException) -> bool:
    """Whether `exc` (a possibly-wrapped activity failure) is a
    `SandboxGoneError` anywhere in its cause chain — see `_first_known_type_name`
    for why the whole chain, not just the root, must be scanned.
    """
    return _first_known_type_name(exc) == "SandboxGoneError"


def _classify_for_workflow(exc: BaseException):
    """`classify()` (core/errors.py) is pure and only knows about real
    exception *instances*. By the time an activity failure reaches workflow
    code it has been wrapped (and re-typed to a generic ApplicationError) by
    Temporal, so reconstruct a same-named instance where we can before
    delegating to the pure classifier. An explicit `non_retryable=True`
    anywhere in the cause chain (e.g. `call_claude` exhausting its own
    per-error-type retry budget) always overrides `classify()`'s verdict,
    since that's a statement about this specific occurrence, not the general
    error class.
    """
    known_name = _first_known_type_name(exc)
    if known_name is not None:
        category, retryable = classify(_KNOWN_EXCEPTION_TYPES[known_name](str(_root_cause(exc))))
    else:
        root = _root_cause(exc)
        type_name = getattr(root, "type", None) or type(root).__name__
        if type_name in ("NotFoundError", "TimeoutError"):
            synthetic = type(type_name, (Exception,), {})
            category, retryable = classify(synthetic(str(root)))
        else:
            category, retryable = classify(root)

    if _any_non_retryable(exc):
        retryable = False
    return category, retryable


@workflow.defn
class FileAnalysisWorkflow:
    @workflow.run
    async def run(self, input: FileInput) -> FileResult:
        priority = fairness_priority(input.tenant_id)
        attempt = workflow.info().attempt

        await workflow.execute_activity(
            mark_file_running,
            MarkFileRunningInput(file_id=input.file_id, attempt=attempt),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=MARK_DB_RETRY_POLICY,
            priority=priority,
            task_queue=TASK_QUEUE_ACTIVITIES,
        )

        sandbox_ids: list[str] = []
        try:
            provision_result = await workflow.execute_activity(
                provision_sandbox,
                ProvisionInput(
                    s3_key=input.s3_key,
                    sanitized_filename=input.sanitized_filename,
                    file_id=input.file_id,
                ),
                start_to_close_timeout=PROVISION_SANDBOX_START_TO_CLOSE_TIMEOUT,
                retry_policy=PROVISION_SANDBOX_RETRY_POLICY,
                priority=priority,
                task_queue=TASK_QUEUE_ACTIVITIES,
            )
            sandbox_id = provision_result.sandbox_id
            sandbox_ids.append(sandbox_id)
            # Recovery state (§8.2a): `latest_snapshot_id` is the restore point
            # a mid-loop SandboxGoneError recovers into; `snapshot_lag` counts
            # run_python successes since the last *confirmed* snapshot (the
            # per-turn snapshot in exec_tool is best-effort) — recovery is only
            # attempted while it's 0, so a restore is always known-current, not
            # merely assumed so.
            latest_snapshot_id = provision_result.snapshot_id
            snapshot_lag = 0
            recoveries_used = 0
            max_recoveries = settings.sandbox_max_recoveries

            messages: list[dict] = [
                {
                    "role": "user",
                    "content": build_initial_user_message(
                        input.sanitized_filename, input.original_filename, input.size_bytes
                    ),
                }
            ]

            usage = UsageTotals()
            report: dict | None = None
            turns_used = 0
            max_turns = settings.agent_max_turns

            turn = 0
            while True:
                turns_used = turn + 1
                last = bool(max_turns) and turn == max_turns - 1
                if last:
                    messages.append({"role": "user", "content": TURN_LIMIT_MESSAGE})

                resp = await workflow.execute_activity(
                    call_claude,
                    LLMInput(messages=list(messages), force_report=last),
                    start_to_close_timeout=CALL_CLAUDE_START_TO_CLOSE_TIMEOUT,
                    schedule_to_start_timeout=CALL_CLAUDE_SCHEDULE_TO_START_TIMEOUT,
                    retry_policy=CALL_CLAUDE_RETRY_POLICY,
                    priority=priority,
                    task_queue=TASK_QUEUE_LLM,
                )
                usage = accumulate_usage(usage, resp.usage)
                messages.append({"role": "assistant", "content": resp.content})

                if resp.stop_reason != "tool_use":
                    break

                tool_use_blocks = [b for b in resp.content if b.get("type") == "tool_use"]
                results = []
                done = False
                for block in tool_use_blocks:
                    if block["name"] == "write_report":
                        try:
                            report = validate_report(block["input"])
                            results.append(
                                build_tool_result_block(block["id"], "report accepted", is_error=False)
                            )
                            done = True
                        except ReportValidationError as e:
                            results.append(
                                build_tool_result_block(block["id"], f"invalid report: {e}", is_error=True)
                            )
                    else:
                        while True:
                            try:
                                out = await workflow.execute_activity(
                                    exec_tool,
                                    ExecToolInput(
                                        sandbox_id=sandbox_id,
                                        tool_name=block["name"],
                                        tool_input=block.get("input", {}),
                                        turn_index=turn,
                                    ),
                                    start_to_close_timeout=EXEC_TOOL_START_TO_CLOSE_TIMEOUT,
                                    retry_policy=EXEC_TOOL_RETRY_POLICY,
                                    priority=priority,
                                    task_queue=TASK_QUEUE_ACTIVITIES,
                                )
                                break
                            except Exception as e:
                                if (
                                    not _is_sandbox_gone(e)
                                    or snapshot_lag != 0
                                    or recoveries_used >= max_recoveries
                                ):
                                    raise
                                recoveries_used += 1
                                workflow.logger.warning(
                                    "sandbox %s lost mid-loop (recovery %d/%d); "
                                    "restoring from snapshot %s",
                                    sandbox_id,
                                    recoveries_used,
                                    max_recoveries,
                                    latest_snapshot_id,
                                )
                                recover_result = await workflow.execute_activity(
                                    recover_sandbox,
                                    RecoverSandboxInput(
                                        snapshot_id=latest_snapshot_id,
                                        sanitized_filename=input.sanitized_filename,
                                        file_id=input.file_id,
                                    ),
                                    start_to_close_timeout=RECOVER_SANDBOX_START_TO_CLOSE_TIMEOUT,
                                    retry_policy=RECOVER_SANDBOX_RETRY_POLICY,
                                    priority=priority,
                                    task_queue=TASK_QUEUE_ACTIVITIES,
                                )
                                sandbox_id = recover_result.sandbox_id
                                sandbox_ids.append(sandbox_id)

                        if block["name"] == "run_python":
                            if out.snapshot_id:
                                latest_snapshot_id = out.snapshot_id
                                snapshot_lag = 0
                            else:
                                snapshot_lag += 1

                        results.append(
                            build_tool_result_block(block["id"], out.content, is_error=out.is_error)
                        )

                messages.append(build_tool_results_message(results))
                if done:
                    break

                turn += 1
                if max_turns and turn >= max_turns:
                    # Safety net: should be unreachable because `last` forces
                    # write_report on turn max_turns - 1 with tool_choice
                    # pinned to it, which always ends the loop above. Kept as
                    # a hard backstop against an unexpected model response
                    # shape (e.g. it ignores tool_choice) so the loop cannot
                    # spin forever.
                    break

            if report is None:
                # The model stopped (end_turn / max_tokens / ...) without ever
                # calling write_report, and we are not in the forced-report
                # turn (which always yields either a report or a hard stop
                # above). This is a genuine failure, not a hang.
                raise ApplicationError(
                    "agent loop ended without a report",
                    type="INTERNAL",
                )

            await workflow.execute_activity(
                mark_file_succeeded,
                MarkFileSucceededInput(
                    file_id=input.file_id,
                    report=report,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    turn_count=turns_used,
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=MARK_DB_RETRY_POLICY,
                priority=priority,
                task_queue=TASK_QUEUE_ACTIVITIES,
            )
            return FileResult(status=FileStatus.SUCCEEDED.value)

        except ValidationError as e:
            # A ValidationError raised directly by workflow code (not via an
            # activity boundary — those arrive as wrapped ActivityError and
            # are handled below). Non-retryable: the input itself is bad, so
            # write the terminal row on this single attempt.
            await workflow.execute_activity(
                mark_file_failed,
                MarkFileFailedInput(
                    file_id=input.file_id,
                    error_category=ErrorCategory.VALIDATION.value,
                    error_message=str(e),
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=MARK_DB_RETRY_POLICY,
                priority=priority,
                task_queue=TASK_QUEUE_ACTIVITIES,
            )
            raise ApplicationError(str(e), type="ValidationError", non_retryable=True) from e

        except Exception as e:
            category, retryable = _classify_for_workflow(e)

            if not retryable:
                # Both ValidationError (bad input) and LLMClientError
                # (Anthropic 4xx) are deterministic failures — retrying the
                # whole child workflow would just reproduce the same failure
                # at the cost of real money for the LLM case. Reached via an
                # activity boundary (e.g. provision_sandbox, call_claude)
                # whose exception arrived here wrapped as ActivityError.
                # `non_retryable=True` on the raised ApplicationError is
                # honored by Temporal regardless of the child workflow retry
                # policy's `non_retryable_error_types` list (which only names
                # "ValidationError" per §6.4) — this is what keeps a 4xx to
                # exactly one LLM call instead of re-billing it on retry.
                await workflow.execute_activity(
                    mark_file_failed,
                    MarkFileFailedInput(
                        file_id=input.file_id,
                        error_category=category.value,
                        error_message=str(e),
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=MARK_DB_RETRY_POLICY,
                    priority=priority,
                    task_queue=TASK_QUEUE_ACTIVITIES,
                )
                raise ApplicationError(str(e), type=category.name, non_retryable=True) from e

            # `mark_file_failed` is only written on the final attempt (§7.2) —
            # intermediate attempts leave the row RUNNING so the UI doesn't
            # flicker to "failed" and back while Temporal retries.
            if workflow.info().attempt >= 3:
                await workflow.execute_activity(
                    mark_file_failed,
                    MarkFileFailedInput(
                        file_id=input.file_id,
                        error_category=category.value,
                        error_message=str(e),
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=MARK_DB_RETRY_POLICY,
                    priority=priority,
                    task_queue=TASK_QUEUE_ACTIVITIES,
                )
            raise

        finally:
            # The finally block is the sandbox's owner: runs on success,
            # failure, cancellation, and every retry attempt. A recovered file
            # may have created more than one sandbox (the "gone" one may not
            # actually be dead — a false positive from a transient
            # control-plane blip — so it must still be cleaned up, not just
            # the latest one). One failing terminate must not skip the rest.
            for sb_id in sandbox_ids:
                try:
                    await workflow.execute_activity(
                        terminate_sandbox,
                        TerminateInput(sandbox_id=sb_id),
                        start_to_close_timeout=TERMINATE_SANDBOX_START_TO_CLOSE_TIMEOUT,
                        retry_policy=TERMINATE_SANDBOX_RETRY_POLICY,
                        priority=priority,
                        task_queue=TASK_QUEUE_TERMINATE,
                    )
                except Exception:
                    pass
