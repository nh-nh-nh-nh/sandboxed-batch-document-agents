"""Activity-body tests for `sbda.temporal.activities.sandbox`, with `modal`
and the S3 client patched at the client boundary. SPEC.md §14.2.
"""

from __future__ import annotations

import types

import pytest

from sbda.config import settings
from sbda.core.errors import SandboxGoneError, ValidationError
from sbda.temporal.activities import sandbox as sandbox_mod


class FakeNotFoundError(Exception):
    pass


class FakeExecProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = types.SimpleNamespace(read=lambda: stdout)
        self.stderr = types.SimpleNamespace(read=lambda: stderr)
        self.returncode = returncode
        self._waited = False

    def wait(self):
        self._waited = True
        return self.returncode


class FakeOpenFile:
    def __init__(self, sandbox, path, mode):
        self.sandbox = sandbox
        self.path = path
        self.sandbox.written.setdefault(path, b"")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.sandbox.written[self.path] += data


class _FakeAsyncMethod:
    """Mirrors the real Modal SDK shape: a sync-callable object that also
    exposes `.aio(...)` — activity code always calls the `.aio()` form.
    """

    def __init__(self, fn):
        self._fn = fn

    async def aio(self, *args, **kwargs):
        return self._fn(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        return self._fn(*args, **kwargs)


class FakeImage:
    """A fake directory-snapshot `Image`: just the subset of a sandbox's
    `.written` dict that fell under the snapshotted path, replayable into
    another `FakeSandbox` via `mount_image`.
    """

    _registry: dict[str, FakeImage] = {}
    _counter = 0

    def __init__(self, object_id: str, contents: dict[str, bytes]):
        self.object_id = object_id
        self.contents = dict(contents)

    @classmethod
    def from_id(cls, image_id):
        img = cls._registry.get(image_id)
        if img is None:
            raise fake_modal.exception.NotFoundError(image_id)
        return img


class FakeSandbox:
    _registry: dict[str, "FakeSandbox"] = {}

    def __init__(self, object_id):
        self.object_id = object_id
        self.written: dict[str, bytes] = {}
        self.exec_calls: list[tuple] = []
        self.exec_queue: list[tuple[str, str, int]] = []
        self.terminate_calls = 0
        self.terminated = False
        self.mount_calls: list[tuple[str, str]] = []
        self.filesystem = types.SimpleNamespace(
            write_bytes=_FakeAsyncMethod(self._write_bytes),
            write_text=_FakeAsyncMethod(self._write_text),
        )
        self.snapshot_directory = _FakeAsyncMethod(self._snapshot_directory)
        self.mount_image = _FakeAsyncMethod(self._mount_image)
        FakeSandbox._registry[object_id] = self

    def open(self, path, mode="wb"):
        return FakeOpenFile(self, path, mode)

    def _write_bytes(self, data, path):
        self.written[path] = bytes(data)

    def _write_text(self, text, path):
        self.written[path] = text.encode("utf-8")

    def _snapshot_directory(self, path, ttl=None, timeout=55):
        FakeImage._counter += 1
        object_id = f"snap-{FakeImage._counter}"
        prefix = path.rstrip("/") + "/"
        contents = {p: v for p, v in self.written.items() if p == path or p.startswith(prefix)}
        img = FakeImage(object_id, contents)
        FakeImage._registry[object_id] = img
        return img

    def _mount_image(self, path, image):
        self.mount_calls.append((path, image.object_id))
        self.written.update(image.contents)

    def exec(self, *args, **kwargs):
        self.exec_calls.append(args)
        if args[0] == "test" and args[1] == "-s":
            path = args[2]
            ok = len(self.written.get(path, b"")) > 0
            return FakeExecProc(returncode=0 if ok else 1)
        if self.exec_queue:
            stdout, stderr, code = self.exec_queue.pop(0)
        else:
            stdout, stderr, code = "", "", 0
        return FakeExecProc(stdout, stderr, code)

    def terminate(self, wait=False):
        self.terminate_calls += 1
        self.terminated = True

    @classmethod
    def create(cls, **kwargs):
        sb = cls(object_id=f"sb-{len(cls._registry) + 1}")
        sb.create_kwargs = kwargs
        return sb

    @classmethod
    def from_id(cls, sandbox_id):
        sb = cls._registry.get(sandbox_id)
        if sb is None or sb.terminated:
            raise fake_modal.exception.NotFoundError(sandbox_id)
        return sb


fake_modal = types.SimpleNamespace(
    Sandbox=FakeSandbox,
    Image=FakeImage,
    exception=types.SimpleNamespace(NotFoundError=FakeNotFoundError),
)


class ChunkedBody:
    """S3 streaming body fake that only ever supports bounded `.read(n)`."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, amt=None):
        if amt is None:
            raise AssertionError("must never call .read() with no size (whole-object read)")
        chunk = self._data[self._pos : self._pos + amt]
        self._pos += len(chunk)
        return chunk


class FakeS3Client:
    def __init__(self, data: bytes):
        self._data = data
        self.get_object_calls = []

    def get_object(self, Bucket, Key):
        self.get_object_calls.append((Bucket, Key))
        return {"Body": ChunkedBody(self._data)}


@pytest.fixture(autouse=True)
def patched_modal(monkeypatch):
    FakeSandbox._registry.clear()
    FakeImage._registry.clear()
    FakeImage._counter = 0
    monkeypatch.setattr(sandbox_mod, "modal", fake_modal)
    monkeypatch.setattr(sandbox_mod, "get_app", lambda: "fake-app")
    monkeypatch.setattr(sandbox_mod, "get_image", lambda: "fake-image")
    yield


async def test_provision_sandbox_uses_isolation_kwargs(monkeypatch):
    s3 = FakeS3Client(b"a,b\n1,2\n")
    monkeypatch.setattr(sandbox_mod, "get_s3_client", lambda: s3)

    result = await sandbox_mod.provision_sandbox(
        sandbox_mod.ProvisionInput(s3_key="k", sanitized_filename="in.csv", file_id="f1")
    )

    sb = FakeSandbox._registry[result.sandbox_id]
    assert sb.create_kwargs["block_network"] is True
    assert sb.create_kwargs["timeout"] == settings.sandbox_timeout_s
    assert sb.create_kwargs["cpu"] == settings.sandbox_cpu
    assert sb.create_kwargs["memory"] == settings.sandbox_memory_mb
    assert sb.create_kwargs["workdir"] == "/work"


async def test_provision_sandbox_streams_in_chunks_never_full_read(monkeypatch):
    payload = b"x" * (600 * 1024)  # bigger than one chunk
    s3 = FakeS3Client(payload)
    monkeypatch.setattr(sandbox_mod, "get_s3_client", lambda: s3)

    result = await sandbox_mod.provision_sandbox(
        sandbox_mod.ProvisionInput(s3_key="k", sanitized_filename="big.csv", file_id="f1")
    )
    sb = FakeSandbox._registry[result.sandbox_id]
    assert sb.written["/work/input/big.csv"] == payload


async def test_provision_sandbox_returns_sandbox_id(monkeypatch):
    s3 = FakeS3Client(b"data")
    monkeypatch.setattr(sandbox_mod, "get_s3_client", lambda: s3)
    result = await sandbox_mod.provision_sandbox(
        sandbox_mod.ProvisionInput(s3_key="k", sanitized_filename="f.csv", file_id="f1")
    )
    assert result.sandbox_id.startswith("sb-")


async def test_provision_sandbox_zero_byte_file_raises_validation_error(monkeypatch):
    s3 = FakeS3Client(b"")
    monkeypatch.setattr(sandbox_mod, "get_s3_client", lambda: s3)
    with pytest.raises(ValidationError):
        await sandbox_mod.provision_sandbox(
            sandbox_mod.ProvisionInput(s3_key="k", sanitized_filename="empty.csv", file_id="f1")
        )


async def test_exec_tool_resolves_sandbox_with_from_id_every_call():
    sb = FakeSandbox.create()
    sb.exec_queue.append(("ok\n", "", 0))

    result = await sandbox_mod.exec_tool(
        sandbox_mod.ExecToolInput(sandbox_id=sb.object_id, tool_name="run_python", tool_input={"code": "print('ok')"})
    )
    assert "ok" in result.content
    # first call was the run_python exec — confirm resolution went through from_id
    assert FakeSandbox._registry[sb.object_id] is sb


async def test_exec_tool_from_id_not_found_raises_sandbox_gone_error():
    with pytest.raises(SandboxGoneError):
        await sandbox_mod.exec_tool(
            sandbox_mod.ExecToolInput(sandbox_id="does-not-exist", tool_name="run_python", tool_input={"code": "1"})
        )


async def test_exec_tool_terminated_sandbox_raises_sandbox_gone_error():
    sb = FakeSandbox.create()
    sb.terminated = True
    with pytest.raises(SandboxGoneError):
        await sandbox_mod.exec_tool(
            sandbox_mod.ExecToolInput(sandbox_id=sb.object_id, tool_name="run_python", tool_input={"code": "1"})
        )


async def test_run_python_writes_code_to_file_never_shell_interpolated():
    sb = FakeSandbox.create()
    sb.exec_queue.append(("done\n", "", 0))
    dangerous_code = "import os; os.system('rm -rf /'); print('done')"

    await sandbox_mod.exec_tool(
        sandbox_mod.ExecToolInput(sandbox_id=sb.object_id, tool_name="run_python", tool_input={"code": dangerous_code})
    )

    # The code was written to a cell file via sb.open(), not passed as a shell arg.
    written_paths = list(sb.written.keys())
    assert any(p.startswith("/work/.agent/cell_") for p in written_paths)
    cell_path = next(p for p in written_paths if p.startswith("/work/.agent/cell_"))
    assert sb.written[cell_path].decode("utf-8") == dangerous_code

    # None of the exec() calls received the code as a raw shell argument.
    for call in sb.exec_calls:
        assert dangerous_code not in call
        assert all("rm -rf" not in str(a) for a in call)


async def test_terminate_sandbox_on_already_gone_succeeds():
    await sandbox_mod.terminate_sandbox(sandbox_mod.TerminateInput(sandbox_id="never-existed"))


async def test_terminate_sandbox_is_idempotent_called_twice():
    sb = FakeSandbox.create()
    await sandbox_mod.terminate_sandbox(sandbox_mod.TerminateInput(sandbox_id=sb.object_id))
    assert sb.terminate_calls == 1
    # second call: sandbox now reports terminated -> from_id raises NotFoundError -> swallowed
    await sandbox_mod.terminate_sandbox(sandbox_mod.TerminateInput(sandbox_id=sb.object_id))


async def test_provision_sandbox_returns_snapshot_id(monkeypatch):
    s3 = FakeS3Client(b"data")
    monkeypatch.setattr(sandbox_mod, "get_s3_client", lambda: s3)

    result = await sandbox_mod.provision_sandbox(
        sandbox_mod.ProvisionInput(s3_key="k", sanitized_filename="f.csv", file_id="f1")
    )

    assert result.snapshot_id.startswith("snap-")
    snapshot = FakeImage.from_id(result.snapshot_id)
    assert "/work/input/f.csv" in snapshot.contents


async def test_exec_tool_run_python_returns_snapshot_id_on_success():
    sb = FakeSandbox.create()
    sb.exec_queue.append(("ok\n", "", 0))

    result = await sandbox_mod.exec_tool(
        sandbox_mod.ExecToolInput(
            sandbox_id=sb.object_id, tool_name="run_python", tool_input={"code": "print(1)"}
        )
    )

    assert result.snapshot_id is not None
    assert FakeImage.from_id(result.snapshot_id) is not None


async def test_exec_tool_read_file_does_not_snapshot():
    sb = FakeSandbox.create()
    sb.written["/work/input/f.csv"] = b"a,b\n1,2\n"

    result = await sandbox_mod.exec_tool(
        sandbox_mod.ExecToolInput(
            sandbox_id=sb.object_id,
            tool_name="read_file",
            tool_input={"path": "/work/input/f.csv"},
        )
    )

    assert result.snapshot_id is None


async def test_exec_tool_snapshot_failure_does_not_fail_tool_call(monkeypatch):
    sb = FakeSandbox.create()
    sb.exec_queue.append(("ok\n", "", 0))

    def _boom(path, ttl=None, timeout=55):
        raise RuntimeError("snapshot RPC failed")

    monkeypatch.setattr(sb, "snapshot_directory", _FakeAsyncMethod(_boom))

    result = await sandbox_mod.exec_tool(
        sandbox_mod.ExecToolInput(
            sandbox_id=sb.object_id, tool_name="run_python", tool_input={"code": "print(1)"}
        )
    )

    assert "ok" in result.content
    assert result.is_error is False
    assert result.snapshot_id is None


async def test_recover_sandbox_mounts_snapshot_and_returns_new_sandbox_id():
    original = FakeSandbox.create()
    original.written["/work/input/f.csv"] = b"a,b\n1,2\n"
    snapshot = original._snapshot_directory("/work")

    result = await sandbox_mod.recover_sandbox(
        sandbox_mod.RecoverSandboxInput(
            snapshot_id=snapshot.object_id, sanitized_filename="f.csv", file_id="f1"
        )
    )

    recovered = FakeSandbox._registry[result.sandbox_id]
    assert recovered.written["/work/input/f.csv"] == b"a,b\n1,2\n"
    assert recovered.mount_calls == [("/work", snapshot.object_id)]


async def test_recover_sandbox_raises_sandbox_gone_error_if_input_missing_after_mount():
    original = FakeSandbox.create()
    # nothing written under /work -> the snapshot is empty, so the mounted
    # sandbox will be missing the input file.
    snapshot = original._snapshot_directory("/work")

    with pytest.raises(SandboxGoneError):
        await sandbox_mod.recover_sandbox(
            sandbox_mod.RecoverSandboxInput(
                snapshot_id=snapshot.object_id, sanitized_filename="f.csv", file_id="f1"
            )
        )
