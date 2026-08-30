# STUB — owned by the backend-foundation slice (see SPEC.md §5.2, §14.1 `test_validation.py`).
#
# Batch validation rules. Reconcile against the backend-foundation PR's real
# `core/validation.py`.

from __future__ import annotations

from sbda.core.errors import ValidationError

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".xlsm"}


class NoFilesError(ValidationError):
    pass


class TooManyFilesError(ValidationError):
    pass


class UnsupportedExtensionError(ValidationError):
    pass


class FileTooLargeError(ValidationError):
    pass


class SubmissionTooLargeError(ValidationError):
    pass
