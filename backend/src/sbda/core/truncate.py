"""Head+tail tool-output truncation (SPEC.md §9.4).

Bounds a single tool result to a byte cap before it enters workflow state,
without ever splitting a multi-byte UTF-8 codepoint.
"""

from __future__ import annotations


def _marker(n: int) -> str:
    return f"\n…[truncated {n} bytes]…\n"


def truncate_output(text: str, max_bytes: int) -> str:
    """Truncate ``text`` to (approximately) ``max_bytes`` UTF-8 bytes.

    - Text already within the cap is returned byte-identical, no marker added.
    - Text over the cap keeps a head and a tail portion, joined by a marker
      naming exactly how many bytes were dropped.
    - Truncation never splits a multi-byte UTF-8 codepoint: partial trailing
      bytes at each boundary are dropped rather than emitted as invalid UTF-8.
    - ``max_bytes <= 0`` returns only the marker, naming the full length.
    """

    if text == "":
        return text

    encoded = text.encode("utf-8")
    total = len(encoded)

    if max_bytes <= 0:
        return _marker(total)

    if total <= max_bytes:
        return text

    head_budget = max_bytes // 2
    tail_budget = max_bytes - head_budget

    head = encoded[:head_budget].decode("utf-8", errors="ignore")
    tail = (
        encoded[total - tail_budget :].decode("utf-8", errors="ignore")
        if tail_budget > 0
        else ""
    )

    kept_bytes = len(head.encode("utf-8")) + len(tail.encode("utf-8"))
    n = total - kept_bytes

    return f"{head}{_marker(n)}{tail}"
