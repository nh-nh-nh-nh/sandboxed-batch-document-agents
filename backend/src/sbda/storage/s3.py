# STUB — owned by the backend-foundation slice (see SPEC.md §4, §2).
#
# Minimal boto3 client wrapper. `sbda.temporal.activities.sandbox` imports
# `get_s3_client` (or constructs its own client the same way) to stream an
# object from S3 into a Modal sandbox in chunks. Reconcile against the
# backend-foundation PR's real `storage/s3.py`.

from __future__ import annotations

import boto3

from sbda.config import settings


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
