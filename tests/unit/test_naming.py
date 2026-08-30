from __future__ import annotations

import re

from hypothesis import given
from hypothesis import strategies as st

from sbda.core.naming import build_s3_key, sanitize_filename

VALID_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


def test_spaces_replaced():
    assert sanitize_filename("sales 2024.xlsx") == "sales_2024.xlsx"


def test_traversal_no_dot_dot_or_slash_survives():
    result = sanitize_filename("../../etc/passwd")
    assert "/" not in result
    assert not result.startswith("..")


def test_backslash_traversal_replaced():
    result = sanitize_filename("..\\..\\win.ini")
    assert "\\" not in result
    assert not result.startswith("..")


def test_absolute_path_leading_separator_stripped():
    assert sanitize_filename("/absolute/path.csv") == "path.csv"


def test_non_ascii_replaced_extension_preserved():
    result = sanitize_filename("名前.csv")
    assert result.endswith(".csv")
    assert VALID_NAME_RE.match(result)


def test_long_name_truncated_to_200():
    result = sanitize_filename("a" * 300 + ".csv")
    assert len(result) == 200


def test_leading_dot_does_not_produce_empty_name():
    result = sanitize_filename(".hidden")
    assert result != ""
    assert VALID_NAME_RE.match(result)


def test_empty_input_falls_back_to_placeholder():
    result = sanitize_filename("")
    assert result != ""
    assert VALID_NAME_RE.match(result)


def test_windows_device_names_pass_through():
    assert sanitize_filename("con.csv") == "con.csv"
    assert sanitize_filename("nul") == "nul"


def test_shell_metacharacters_replaced():
    result = sanitize_filename("file;rm -rf /.csv")
    for ch in [";", " ", "/"]:
        assert ch not in result
    assert VALID_NAME_RE.match(result)


@given(st.text(min_size=0, max_size=500))
def test_output_always_matches_allowed_pattern(name: str):
    result = sanitize_filename(name)
    assert VALID_NAME_RE.match(result), repr(result)


# --- S3 key builder ---------------------------------------------------------


def test_s3_key_shape():
    key = build_s3_key("tenant1", "sub1", "file1", "report.csv")
    assert key == "tenants/tenant1/submissions/sub1/file1/report.csv"


def test_s3_key_duplicate_names_produce_different_keys():
    key1 = build_s3_key("t", "s", "file-a", "report.csv")
    key2 = build_s3_key("t", "s", "file-b", "report.csv")
    assert key1 != key2


def test_s3_key_never_contains_dotdot_or_double_slash():
    key = build_s3_key("t", "s", "f", "../../etc/passwd")
    assert ".." not in key
    assert "//" not in key
