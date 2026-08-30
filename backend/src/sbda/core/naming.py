# STUB — owned by the backend-foundation slice (see SPEC.md §4.1, §14.1 `test_naming.py`).
#
# Filename sanitization + S3 key builder. Reconcile against the
# backend-foundation PR's real `core/naming.py`.

from __future__ import annotations

import re

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/")
    name = name.split("/")[-1]
    sanitized = _UNSAFE.sub("_", name)[:200]
    if not sanitized or sanitized.strip("_") == "" and sanitized == "":
        sanitized = "file"
    if not sanitized:
        sanitized = "file"
    return sanitized


def build_s3_key(tenant_id: str, submission_id: str, file_id: str, sanitized_filename: str) -> str:
    return f"tenants/{tenant_id}/submissions/{submission_id}/{file_id}/{sanitized_filename}"
