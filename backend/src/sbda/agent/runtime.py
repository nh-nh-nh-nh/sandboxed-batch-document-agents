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

_DELIMITER_TOKENS = ("<stdout>", "</stdout>", "<stderr>", "</stderr>")


def cell_path(turn_index: int) -> str:
    return f"{CELL_DIR}/cell_{turn_index}.py"


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
