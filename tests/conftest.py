"""Shared test factories (SPEC.md §2, §14)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass
class FileInput:
    """A minimal in-memory description of one file for tests, independent of
    any particular layer's model (validation, DB row, S3 upload, ...)."""

    filename: str
    content: bytes = b"a,b,c\n1,2,3\n"
    content_type: str = "text/csv"

    @property
    def size_bytes(self) -> int:
        return len(self.content)


def make_file_input(filename: str = "sample.csv", size_bytes: int | None = None) -> FileInput:
    content = b"a,b,c\n1,2,3\n" if size_bytes is None else b"x" * size_bytes
    return FileInput(filename=filename, content=content)


def make_report_payload(
    summary: str = "A tidy 3-row CSV with no missing data.",
    findings: list[dict] | None = None,
) -> dict:
    if findings is None:
        findings = [
            {"title": "Clean data", "detail": "No missing values found.", "severity": "info"}
        ]
    return {"summary": summary, "findings": findings}


def make_llm_text_response(text: str = "ok") -> dict:
    """A minimal stand-in for an Anthropic Messages API response with no
    tool use — used by tests that only need `stop_reason` plumbing."""

    return {
        "id": f"msg_{uuid.uuid4().hex[:12]}",
        "role": "assistant",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0},
    }


def make_llm_tool_use_response(
    tool_name: str, tool_input: dict, tool_use_id: str | None = None
) -> dict:
    """A minimal stand-in for an Anthropic Messages API response that calls
    exactly one tool."""

    return {
        "id": f"msg_{uuid.uuid4().hex[:12]}",
        "role": "assistant",
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                "id": tool_use_id or f"toolu_{uuid.uuid4().hex[:12]}",
                "name": tool_name,
                "input": tool_input,
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0},
    }
