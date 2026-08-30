"""`provision_sandbox` / `exec_tool` / `terminate_sandbox` activities.

See SPEC.md §8.2-§8.4. All three are plain functions decorated with
`@activity.defn` — `modal` is imported at module scope and every call goes
through `modal.Sandbox.*`, so tests patch `modal.Sandbox` (and friends) to
avoid any real network/Modal call.
"""

from __future__ import annotations

from dataclasses import dataclass

import modal
from temporalio import activity

from sbda.agent.runtime import (
    cell_path,
    render_read_file_source,
    render_run_python_source,
    render_tool_output,
)
from sbda.config import settings
from sbda.core.errors import SandboxGoneError, ValidationError
from sbda.sandboxes.modal_image import get_app, get_image
from sbda.storage.s3 import get_s3_client

# Streamed transfer chunk size — never `.read()` the whole S3 object at once.
_TRANSFER_CHUNK_BYTES = 256 * 1024


@dataclass
class ProvisionInput:
    s3_key: str
    sanitized_filename: str
    file_id: str


@dataclass
class ProvisionResult:
    sandbox_id: str


@dataclass
class ExecToolInput:
    sandbox_id: str
    tool_name: str
    tool_input: dict
    turn_index: int = 0


@dataclass
class ExecToolResult:
    content: str
    is_error: bool


@dataclass
class TerminateInput:
    sandbox_id: str


def _sandbox_input_path(sanitized_filename: str) -> str:
    return f"/work/input/{sanitized_filename}"


@activity.defn
async def provision_sandbox(input: ProvisionInput) -> ProvisionResult:
    app = get_app()
    image = get_image()

    sb = modal.Sandbox.create(
        app=app,
        image=image,
        timeout=settings.sandbox_timeout_s,
        block_network=True,
        cpu=settings.sandbox_cpu,
        memory=settings.sandbox_memory_mb,
        workdir="/work",
    )

    s3 = get_s3_client()
    obj = s3.get_object(Bucket=settings.s3_bucket, Key=input.s3_key)
    body = obj["Body"]

    dest_path = _sandbox_input_path(input.sanitized_filename)
    total_bytes = 0
    buf = bytearray()
    while True:
        chunk = body.read(_TRANSFER_CHUNK_BYTES)
        if not chunk:
            break
        buf.extend(chunk)
        total_bytes += len(chunk)
        if activity.in_activity():
            activity.heartbeat(f"transferred {total_bytes} bytes")
    await sb.filesystem.write_bytes.aio(bytes(buf), dest_path)

    check = sb.exec("test", "-s", dest_path)
    check.wait()
    if check.returncode != 0:
        raise ValidationError(
            f"file {input.sanitized_filename!r} landed empty in the sandbox"
        )

    return ProvisionResult(sandbox_id=sb.object_id)


def _resolve_sandbox(sandbox_id: str):
    try:
        return modal.Sandbox.from_id(sandbox_id)
    except modal.exception.NotFoundError as e:
        raise SandboxGoneError(f"sandbox {sandbox_id} not found") from e


@activity.defn
async def exec_tool(input: ExecToolInput) -> ExecToolResult:
    sb = _resolve_sandbox(input.sandbox_id)

    if input.tool_name == "run_python":
        source = render_run_python_source(input.tool_input.get("code", ""))
    elif input.tool_name == "read_file":
        source = render_read_file_source(
            input.tool_input.get("path", ""),
            input.tool_input.get("max_bytes", settings.tool_output_max_bytes),
        )
    else:
        return ExecToolResult(
            content=f"<stdout></stdout>\n<stderr>unknown tool: {input.tool_name}</stderr>\nexit_code: 1",
            is_error=True,
        )

    path = cell_path(input.turn_index)
    try:
        await sb.filesystem.write_text.aio(source, path)

        proc = sb.exec(
            "python",
            path,
            timeout=settings.tool_exec_timeout_s,
        )
        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        proc.wait()
        exit_code = proc.returncode
    except modal.exception.NotFoundError as e:
        raise SandboxGoneError(f"sandbox {input.sandbox_id} gone during exec") from e
    except Exception as e:
        # Any other "the sandbox itself is gone" style error from the SDK
        # (terminated mid-exec, preempted, OOM-killed) is treated the same
        # way: a full-workflow retry, never a partial-result activity failure.
        if _looks_like_sandbox_gone(e):
            raise SandboxGoneError(str(e)) from e
        raise

    rendered = render_tool_output(
        stdout, stderr, exit_code, settings.tool_output_max_bytes
    )
    return ExecToolResult(content=rendered.content, is_error=rendered.is_error)


def _looks_like_sandbox_gone(exc: Exception) -> bool:
    name = type(exc).__name__
    return name in ("NotFoundError", "SandboxTerminatedError") or "terminat" in str(exc).lower()


@activity.defn
async def terminate_sandbox(input: TerminateInput) -> None:
    try:
        sb = modal.Sandbox.from_id(input.sandbox_id)
        sb.terminate(wait=False)
    except modal.exception.NotFoundError:
        pass  # already gone — success, idempotent by construction
