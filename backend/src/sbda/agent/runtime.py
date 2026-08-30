"""Python payloads executed inside the Modal sandbox, and the tool-output
renderer that turns raw stdout/stderr/exit_code into the envelope the model
sees.

Two concerns live here, both dictated by SPEC.md §9.4 / §10:

1. **Sandbox-side source generation.** `run_python`'s code is written verbatim
   to a cell file via `sb.open()` and executed as `python <path>` — never
   interpolated into a shell command. `read_file`'s containment check and
   truncation also run *inside* the sandbox as a small generated script, with
   the caller-supplied path embedded via `json.dumps()` (a safe Python string
   literal), never via raw f-string/format interpolation of untrusted text.
2. **Delimiter-spoofing-resistant rendering.** Every sandbox tool result is
   rendered into a `<stdout>...</stdout><stderr>...</stderr>exit_code: N`
   envelope. Untrusted spreadsheet content can end up in stdout/stderr (a
   printed cell value, a traceback quoting a column name, etc.), so any literal
   occurrence of the envelope's own delimiter tokens inside that content is
   neutralized before rendering — otherwise an injected `</stdout>` could make
   the envelope look like it closed early to anything that parses it
   (including, worst case, a human skimming the transcript). This is what
   `tests/unit/test_tool_rendering.py` pins down.
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass

from sbda.core.truncate import truncate_output as truncate

CELL_DIR = "/work/.agent"

# `VERSIONS_DIR` is where `exec_tool` snapshots a copy of the input file
# before each `run_python` call actually runs (see `exec_tool` in
# `temporal/activities/sandbox.py`). It is scoped per `file_id` so that, if
# this path is ever backed by a mounted Modal Volume instead of the
# sandbox's own ephemeral disk, the same versioned history would start
# surviving sandbox loss without any call site changing. Today it is plain
# local disk and is lost with the rest of `/work` when the sandbox goes away
# — this only shapes the code for that future swap, it does not implement
# resuming a workflow from a snapshot.
VERSIONS_DIR = "/work/.versions"

_DELIMITER_TOKENS = ("<stdout>", "</stdout>", "<stderr>", "</stderr>")


def cell_path(turn_index: int) -> str:
    return f"{CELL_DIR}/cell_{turn_index}.py"


def version_dir(file_id: str) -> str:
    return f"{VERSIONS_DIR}/{file_id}"


def version_path(file_id: str, turn_index: int, sanitized_filename: str) -> str:
    """Path for the versioned snapshot of `sanitized_filename` taken before
    the `turn_index`-th `run_python` call. `turn_index` is reused as-is from
    the workflow's existing per-tool-call counter (already used by
    `cell_path`), so version numbers may skip between `run_python` calls
    (e.g. a `read_file` call in between) — the sequence is still strictly
    increasing, which is all "latest" needs.
    """
    return f"{version_dir(file_id)}/v{turn_index:04d}_{sanitized_filename}"


def render_run_python_source(code: str) -> str:
    """The source written to the cell file for `run_python`.

    Passed through unchanged — the isolation comes from *how* it reaches the
    sandbox (via `sb.open()`, never a shell), not from rewriting it.
    """
    return code


def render_read_file_source(path: str, max_bytes: int, root: str = "/work") -> str:
    """Generated script for `read_file`: containment check + bounded UTF-8 read.

    `path` is embedded via `json.dumps()` so a value containing quotes,
    backslashes, or newlines cannot break out of the string literal — this is
    not a shell command, but the path is still untrusted (indirectly
    model-controlled), so it gets the same treatment as any other value we
    embed into generated source.

    `root` defaults to `/work` (the real sandbox root) and is only overridden
    in tests, which run this generated script against a temp directory.
    """
    safe_path_literal = json.dumps(path)
    safe_root_literal = json.dumps(root)
    return textwrap.dedent(
        f"""\
        import json
        import os
        import sys

        root = os.path.realpath({safe_root_literal})
        raw_path = {safe_path_literal}
        max_bytes = {int(max_bytes)}

        candidate = raw_path if os.path.isabs(raw_path) else os.path.join(root, raw_path)
        target = os.path.realpath(candidate)

        if target != root and not target.startswith(root + os.sep):
            sys.stderr.write(json.dumps({{"error": "path escapes /work"}}))
            sys.exit(1)

        try:
            with open(target, "rb") as f:
                data = f.read(max_bytes + 1)
        except OSError as e:
            sys.stderr.write(json.dumps({{"error": str(e)}}))
            sys.exit(1)

        was_truncated = len(data) > max_bytes
        data = data[:max_bytes]
        sys.stdout.write(data.decode("utf-8", errors="replace"))
        if was_truncated:
            sys.stderr.write("[read_file: output truncated at max_bytes]")
        """
    )


def _neutralize_delimiters(text: str) -> str:
    """Make it impossible for `text` to contain a literal envelope delimiter.

    HTML-escaping `<`/`>` is sufficient and reversible-enough for a human or
    model to still read the content; it just guarantees `<stdout>`,
    `</stdout>`, `<stderr>`, `</stderr>` cannot appear verbatim inside the
    envelope's payload.
    """
    return text.replace("<", "&lt;").replace(">", "&gt;")


@dataclass(frozen=True)
class RenderedToolOutput:
    content: str
    is_error: bool


def render_tool_output(
    stdout: str, stderr: str, exit_code: int, max_bytes: int
) -> RenderedToolOutput:
    """Render a sandbox exec result into the `<stdout>/<stderr>/exit_code`
    envelope, truncating each stream independently and neutralizing any
    injected delimiter tokens first.
    """
    stdout = stdout or ""
    stderr = stderr or ""

    stdout_truncated = truncate(stdout, max_bytes)
    stderr_truncated = truncate(stderr, max_bytes)

    stdout_safe = _neutralize_delimiters(stdout_truncated)
    stderr_safe = _neutralize_delimiters(stderr_truncated)

    content = (
        f"<stdout>{stdout_safe}</stdout>\n"
        f"<stderr>{stderr_safe}</stderr>\n"
        f"exit_code: {exit_code}"
    )
    return RenderedToolOutput(content=content, is_error=exit_code != 0)


# Sanity: every real delimiter token appears in the envelope shape produced
# above exactly as literal text — used by tests to assert well-formedness.
DELIMITER_TOKENS = _DELIMITER_TOKENS
