# STUB — owned by the backend-foundation slice (see SPEC.md §14.1 `test_truncate.py`, §9.4).
#
# Head+tail, codepoint-aware truncation used to bound tool output before it
# enters workflow/Temporal history. Reconcile against the backend-foundation
# PR's real `core/truncate.py`.

from __future__ import annotations


def truncate(text: str, max_bytes: int) -> str:
    """Truncate `text` to at most ~`max_bytes` UTF-8 bytes.

    - If `text` already fits, it is returned unchanged (byte-identical).
    - Otherwise returns head + a `…[truncated N bytes]…` marker + tail, where
      N == original_len - kept_len (in bytes), and the split points never fall
      inside a multi-byte UTF-8 codepoint.
    - `max_bytes == 0` returns only the marker.
    """
    if not text:
        return text

    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    if max_bytes <= 0:
        kept_bytes = 0
        head = ""
        tail = ""
    else:
        half = max_bytes // 2
        head_bytes = half
        tail_bytes = max_bytes - half
        head = _safe_decode_prefix(encoded, head_bytes)
        tail = _safe_decode_suffix(encoded, tail_bytes)
        kept_bytes = len(head.encode("utf-8")) + len(tail.encode("utf-8"))

    truncated_n = len(encoded) - kept_bytes
    marker = f"\n…[truncated {truncated_n} bytes]…\n"
    return f"{head}{marker}{tail}"


def _safe_decode_prefix(encoded: bytes, n: int) -> str:
    n = max(0, min(n, len(encoded)))
    while n > 0:
        try:
            return encoded[:n].decode("utf-8")
        except UnicodeDecodeError:
            n -= 1
    return ""


def _safe_decode_suffix(encoded: bytes, n: int) -> str:
    n = max(0, min(n, len(encoded)))
    total = len(encoded)
    start = total - n
    while start < total:
        try:
            return encoded[start:].decode("utf-8")
        except UnicodeDecodeError:
            start += 1
    return ""
