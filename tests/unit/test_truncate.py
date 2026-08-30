from __future__ import annotations

from sbda.core.truncate import truncate_output


def test_output_shorter_than_cap_returned_identical():
    text = "hello"
    assert truncate_output(text, 1000) == text


def test_output_exactly_at_cap_unchanged():
    text = "x" * 100
    assert truncate_output(text, 100) == text


def test_output_over_cap_has_head_marker_tail():
    text = "A" * 1000
    result = truncate_output(text, 100)
    assert result.startswith("A")
    assert "[truncated" in result
    assert result.endswith("A")
    assert len(result) <= 100 + len("\n…[truncated 1000 bytes]…\n") + 10


def test_reported_n_equals_original_minus_kept():
    text = "B" * 1000
    cap = 100
    result = truncate_output(text, cap)
    marker_start = result.index("[truncated ") + len("[truncated ")
    marker_end = result.index(" bytes]", marker_start)
    n = int(result[marker_start:marker_end])
    kept = len(result.encode("utf-8")) - len(f"\n…[truncated {n} bytes]…\n".encode())
    assert n == len(text.encode("utf-8")) - kept


def test_multibyte_utf8_split_never_produces_invalid_utf8():
    text = "€" * 5000  # 3-byte UTF-8 codepoint
    result = truncate_output(text, 101)  # deliberately not a multiple of 3
    # must not raise
    result.encode("utf-8")


def test_large_string_completes():
    text = "x" * (50 * 1024 * 1024)
    result = truncate_output(text, 32_768)
    assert "[truncated" in result


def test_empty_string_returned_as_is():
    assert truncate_output("", 100) == ""


def test_cap_of_zero_returns_only_marker():
    text = "hello world"
    result = truncate_output(text, 0)
    assert result == f"\n…[truncated {len(text.encode('utf-8'))} bytes]…\n"
