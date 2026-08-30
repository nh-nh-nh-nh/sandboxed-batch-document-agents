"""Filename sanitization and S3 key construction.

This module is a security boundary (SPEC.md §10, §4.1): untrusted,
attacker-controlled filenames pass through here before ever becoming part of
an S3 key or a sandbox path. Tested adversarially in tests/unit/test_naming.py.
"""

from __future__ import annotations

import re

_DISALLOWED_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]")
_LEADING_DOTDOT_RE = re.compile(r"^\.{2,}")
_MAX_NAME_LEN = 200
_FALLBACK = "file"


def sanitize_filename(name: str) -> str:
    """Sanitize an untrusted filename for use in an S3 key / sandbox path.

    - Path separators (``/`` and ``\\``) are treated as directory separators:
      only the final path segment survives, which strips any ``../`` traversal
      and any leading absolute-path separator.
    - Any remaining character outside ``[A-Za-z0-9._-]`` (including non-ASCII
      and shell metacharacters) is replaced with ``_``.
    - A leading run of two or more dots (a residual traversal shape) is
      replaced with underscores; a single leading dot (a "hidden file" name)
      is left alone.
    - Empty input, or input that sanitizes to empty, falls back to a
      non-empty placeholder.
    - The result is truncated to 200 characters.

    The output always matches ``^[A-Za-z0-9._-]{1,200}$``.
    """

    if not name:
        base = _FALLBACK
    else:
        normalized = name.replace("\\", "/")
        base = normalized.rsplit("/", 1)[-1]
        if base == "":
            base = _FALLBACK

    sanitized = _DISALLOWED_CHARS_RE.sub("_", base)
    sanitized = _LEADING_DOTDOT_RE.sub(lambda m: "_" * len(m.group()), sanitized)

    if sanitized == "":
        sanitized = _FALLBACK

    return sanitized[:_MAX_NAME_LEN]


def build_s3_key(tenant_id: str, submission_id: str, file_id: str, filename: str) -> str:
    """Build the S3 object key per SPEC.md §4.1.

    ``tenants/{tenant_id}/submissions/{submission_id}/{file_id}/{sanitized_filename}``

    ``file_id`` guarantees uniqueness even for duplicate filenames within one
    submission.
    """

    sanitized = sanitize_filename(filename)
    return f"tenants/{tenant_id}/submissions/{submission_id}/{file_id}/{sanitized}"
