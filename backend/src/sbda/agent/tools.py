"""Tool JSON schemas for the agentic loop. See SPEC.md §9.3-§9.4.

`run_python` and `read_file` execute inside the Modal sandbox (via
`sbda.temporal.activities.sandbox.exec_tool`); `write_report` is handled
entirely in workflow code and never touches the sandbox.

Tool order matters for prompt caching (§9.1): `cache_control` sits on the
*last* tool definition only, so the whole list must render byte-identically
across every turn of every file. Do not add a per-file dynamic tool.
"""

from __future__ import annotations

RUN_PYTHON_TOOL = {
    "name": "run_python",
    "description": (
        "Execute a fresh Python process inside the sandbox at /work. Each call "
        "is a new interpreter — variables do NOT persist between calls; write "
        "intermediate results to /work/ if you need them in a later call. "
        "Output is truncated at 32 KiB, so print summaries, not whole "
        "dataframes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python source to execute."},
        },
        "required": ["code"],
        "additionalProperties": False,
    },
}

READ_FILE_TOOL = {
    "name": "read_file",
    "description": (
        "Read a path under /work as UTF-8 (invalid bytes replaced), truncated "
        "to max_bytes. Useful for a zero-risk peek at a raw file head before "
        "pandas guesses at a delimiter or header row."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path under /work to read."},
            "max_bytes": {
                "type": "integer",
                "description": "Maximum bytes to return.",
                "default": 32768,
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}

WRITE_REPORT_TOOL = {
    "name": "write_report",
    "description": (
        "Submit the final structured report for this file. Call exactly once, "
        "when your analysis is complete. This ends your work."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "3-8 sentences of prose describing what this file is and what it contains.",
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "detail": {"type": "string"},
                        "severity": {
                            "type": "string",
                            "enum": ["info", "warning", "critical"],
                        },
                    },
                    "required": ["title", "detail", "severity"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "findings"],
        "additionalProperties": False,
    },
    # §9.1 — cache breakpoint on the last tool definition.
    "cache_control": {"type": "ephemeral"},
}

TOOLS = [RUN_PYTHON_TOOL, READ_FILE_TOOL, WRITE_REPORT_TOOL]

SANDBOX_TOOL_NAMES = {"run_python", "read_file"}
