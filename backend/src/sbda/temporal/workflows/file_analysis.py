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
    from sbda.core.errors import LLMClientError, SandboxGoneError, ValidationError, classify
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
        TerminateInput,
        exec_tool,
        provision_sandbox,
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


def _classify_for_workflow(exc: BaseException):
    """`classify()` (core/errors.py) is pure and only knows about real
    exception *instances*. By the time an activity failure reaches workflow
    code it has been wrapped (and re-typed to a generic ApplicationError) by
    Temporal, so reconstruct a same-named instance where we can before
    delegating to the pure classifier.
    """
    root = _root_cause(exc)
    type_name = getattr(root, "type", None) or type(root).__name__

    cls = _KNOWN_EXCEPTION_TYPES.get(type_name)
    if cls is not None:
        return classify(cls(str(root)))

    if type_name in ("RateLimitError", "APIStatusError", "APIConnectionError", "NotFoundError", "TimeoutError"):
        synthetic = type(type_name, (Exception,), {})
        return classify(synthetic(str(root)))

    return classify(root)


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
        )

        sandbox_id: str | None = None
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
            )
            sandbox_id = provision_result.sandbox_id

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
                        out = await workflow.execute_activity(
                            exec_tool,
                            ExecToolInput(
                                sandbox_id=sandbox_id,
                                tool_name=block["name"],
                                tool_input=block.get("input", {}),
                                turn_index=turn,
                                file_id=input.file_id,
                                sanitized_filename=input.sanitized_filename,
                            ),
                            start_to_close_timeout=EXEC_TOOL_START_TO_CLOSE_TIMEOUT,
                            retry_policy=EXEC_TOOL_RETRY_POLICY,
                            priority=priority,
                        )
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
                )
            raise

        finally:
            # The finally block is the sandbox's owner: runs on success,
            # failure, cancellation, and every retry attempt.
            if sandbox_id:
                await workflow.execute_activity(
                    terminate_sandbox,
                    TerminateInput(sandbox_id=sandbox_id),
                    start_to_close_timeout=TERMINATE_SANDBOX_START_TO_CLOSE_TIMEOUT,
                    retry_policy=TERMINATE_SANDBOX_RETRY_POLICY,
                    priority=priority,
                )
