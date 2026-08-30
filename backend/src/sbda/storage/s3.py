"""S3/MinIO storage client (SPEC.md §4).

boto3 wired with an explicit ``endpoint_url`` so the same code path works
against MinIO locally and real S3 in production — no call site differs.
Uploads stream (never buffer the whole object) and enforce a byte cap
*during* the stream (§5.2 step 3).
"""

from __future__ import annotations

import logging
from typing import BinaryIO

import boto3
from botocore.config import Config as BotoConfig

from sbda.config import Settings
from sbda.config import settings as default_settings
from sbda.core.naming import build_s3_key

logger = logging.getLogger(__name__)

__all__ = ["S3Client", "UploadTooLargeError", "build_s3_key"]


class UploadTooLargeError(Exception):
    """Raised when a streamed upload exceeds its byte cap mid-stream."""

    def __init__(self, bytes_read: int, max_bytes: int) -> None:
        self.bytes_read = bytes_read
        self.max_bytes = max_bytes
        super().__init__(f"Upload exceeded cap of {max_bytes} bytes (read {bytes_read})")


class _CappedReader:
    """Wraps a file-like object, raising ``UploadTooLargeError`` mid-stream
    the moment more than ``max_bytes`` has been read. Never buffers the
    object whole — bytes are counted as boto3 pulls them chunk by chunk."""

    def __init__(self, fileobj: BinaryIO, max_bytes: int) -> None:
        self._fileobj = fileobj
        self.max_bytes = max_bytes
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._fileobj.read(size)
        self.bytes_read += len(chunk)
        if self.bytes_read > self.max_bytes:
            raise UploadTooLargeError(self.bytes_read, self.max_bytes)
        return chunk


class S3Client:
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region_name: str,
    ) -> None:
        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
            config=BotoConfig(signature_version="s3v4"),
        )

    @classmethod
    def from_settings(cls, s: Settings | None = None) -> S3Client:
        s = s or default_settings
        return cls(
            endpoint_url=s.s3_endpoint_url,
            bucket=s.s3_bucket,
            aws_access_key_id=s.aws_access_key_id,
            aws_secret_access_key=s.aws_secret_access_key,
            region_name=s.aws_region,
        )

    def upload_fileobj_capped(
        self,
        fileobj: BinaryIO,
        key: str,
        *,
        max_bytes: int,
        content_type: str | None = None,
    ) -> int:
        """Stream ``fileobj`` to ``key``, enforcing ``max_bytes`` during the
        stream. Returns the number of bytes written. On breach, the partial
        object is best-effort deleted and ``UploadTooLargeError`` re-raised.
        """

        capped = _CappedReader(fileobj, max_bytes)
        extra_args = {"ContentType": content_type} if content_type else None
        try:
            self._client.upload_fileobj(capped, self.bucket, key, ExtraArgs=extra_args)
        except UploadTooLargeError:
            self.delete_object(key)
            raise
        return capped.bytes_read

    def get_object_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def get_object_stream(self, key: str):
        """Return the raw boto3 ``StreamingBody`` for ``key`` (chunked reads)."""

        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"]

    def delete_object(self, key: str) -> None:
        """Best-effort delete. Never raises — cleanup paths must not mask the
        original failure that triggered them."""

        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except Exception:
            logger.warning("best-effort delete failed for key=%s", key, exc_info=True)

    def delete_objects(self, keys: list[str]) -> None:
        for key in keys:
            self.delete_object(key)

    def build_key(self, tenant_id: str, submission_id: str, file_id: str, filename: str) -> str:
        return build_s3_key(tenant_id, submission_id, file_id, filename)
