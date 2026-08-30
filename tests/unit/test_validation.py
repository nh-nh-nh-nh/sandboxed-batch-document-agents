from __future__ import annotations

from pathlib import Path

import pytest

from sbda.core.enums import ErrorCategory
from sbda.core.errors import classify
from sbda.core.validation import (
    FileMeta,
    FileTooLargeError,
    NoFilesError,
    SubmissionTooLargeError,
    TooManyFilesError,
    UnsupportedExtensionError,
    ValidationError,
    validate_batch,
    validate_extension,
)

MAX_FILE_BYTES = 1_048_576
MAX_SUBMISSION_BYTES = 104_857_600


def files(n: int, size: int = 10) -> list[FileMeta]:
    return [FileMeta(filename=f"f{i}.csv", size_bytes=size) for i in range(n)]


def test_one_file_accepted():
    validate_batch(files(1))


def test_100_files_accepted():
    validate_batch(files(100))


def test_0_files_raises_no_files_error():
    with pytest.raises(NoFilesError):
        validate_batch([])


def test_101_files_raises_naming_count():
    with pytest.raises(TooManyFilesError) as exc_info:
        validate_batch(files(101))
    assert "101" in str(exc_info.value)


@pytest.mark.parametrize("ext", [".csv", ".tsv", ".xlsx", ".xls", ".xlsm"])
def test_allowed_extensions_accepted(ext):
    validate_batch([FileMeta(filename=f"data{ext}", size_bytes=10)])


@pytest.mark.parametrize("filename", ["data.pdf", "data.zip", "data.exe", "data"])
def test_disallowed_extensions_rejected(filename):
    with pytest.raises(UnsupportedExtensionError) as exc_info:
        validate_batch([FileMeta(filename=filename, size_bytes=10)])
    assert filename in str(exc_info.value)


@pytest.mark.parametrize("filename", ["data.CSV", "data.XlsX"])
def test_extension_case_insensitive(filename):
    validate_batch([FileMeta(filename=filename, size_bytes=10)])


def test_only_final_suffix_counts():
    with pytest.raises(UnsupportedExtensionError):
        validate_batch([FileMeta(filename="report.xlsx.exe", size_bytes=10)])


def test_dotfile_with_no_stem_rejected():
    with pytest.raises(UnsupportedExtensionError):
        validate_batch([FileMeta(filename=".csv", size_bytes=10)])


def test_file_at_exactly_max_bytes_accepted():
    validate_batch([FileMeta(filename="a.csv", size_bytes=MAX_FILE_BYTES)])


def test_file_over_max_bytes_rejected():
    with pytest.raises(FileTooLargeError):
        validate_batch([FileMeta(filename="a.csv", size_bytes=MAX_FILE_BYTES + 1)])


def test_submission_at_exactly_max_bytes_accepted():
    # A custom (smaller) submission cap, independent of the per-file cap, so
    # the "exactly at the boundary" case is exercised cleanly.
    cap = 1000
    batch = [
        FileMeta(filename="a.csv", size_bytes=600),
        FileMeta(filename="b.csv", size_bytes=400),
    ]
    assert sum(f.size_bytes for f in batch) == cap
    validate_batch(batch, max_submission_bytes=cap)


def test_submission_over_max_bytes_rejected():
    cap = 1000
    batch = [
        FileMeta(filename="a.csv", size_bytes=600),
        FileMeta(filename="b.csv", size_bytes=401),
    ]
    with pytest.raises(SubmissionTooLargeError):
        validate_batch(batch, max_submission_bytes=cap)


def test_100_files_each_1_byte_accepted_caps_independent():
    validate_batch([FileMeta(filename=f"f{i}.csv", size_bytes=1) for i in range(100)])


def test_validate_extension_standalone():
    validate_extension("ok.csv")
    with pytest.raises(UnsupportedExtensionError):
        validate_extension("bad.pdf")


# --- fixtures corpus (SPEC.md §14.6) ---------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def test_wrong_extension_fixture_passes_extension_check_but_is_a_validation_case():
    # wrong_extension.xlsx has an allowed extension (routing to VALIDATION
    # happens inside the sandbox, when the content fails to parse as a real
    # spreadsheet — never at the API's extension-check layer).
    validate_extension("wrong_extension.xlsx")
    with pytest.raises(ValidationError) as exc_info:
        validate_extension("wrong_extension.exe")
    assert classify(exc_info.value).category == ErrorCategory.VALIDATION


def test_injection_fixture_has_an_allowed_extension():
    validate_extension("injection.csv")


def test_generated_fixtures_pass_batch_validation():
    if not FIXTURES_DIR.is_dir():
        return  # `make fixtures` not run in this environment
    metas = [
        FileMeta(filename=p.name, size_bytes=p.stat().st_size)
        for p in FIXTURES_DIR.iterdir()
        if p.suffix.lower() in {".csv", ".tsv", ".xlsx", ".xls", ".xlsm"}
    ]
    validate_batch(metas)
