"""
Object storage service (AWS S3).

The application's abstraction over S3. All uploaded media is private: objects are
stored without public ACLs and are read exclusively through short-lived
presigned URLs. The boto3 client is created lazily so importing this module
performs no I/O and tests can mock the client.

Storage keys (not URLs) are what callers persist; access URLs are minted on
demand via :meth:`generate_presigned_url`. Deletion is idempotent.
"""

from __future__ import annotations

import logging
import uuid
from typing import BinaryIO

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when an object storage operation fails unrecoverably."""


class StorageService:
    """Upload, sign, and delete private media objects in S3."""

    def __init__(self) -> None:
        self._s3 = None  # Lazily initialized boto3 client.

    def _client(self):
        if self._s3 is None:
            self._s3 = boto3.client(
                "s3",
                region_name=settings.AWS_S3_REGION_NAME or None,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
                config=BotoConfig(signature_version=settings.AWS_S3_SIGNATURE_VERSION),
            )
        return self._s3

    @property
    def _bucket(self) -> str:
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        if not bucket:
            raise StorageError("AWS_STORAGE_BUCKET_NAME is not configured.")
        return bucket

    @staticmethod
    def build_key(prefix: str, filename: str) -> str:
        """Build a collision-proof object key: ``<prefix>/<uuid><ext>``.

        The original filename is never trusted for the stored key (only its
        extension is preserved), preventing path traversal and collisions.
        """
        suffix = ""
        if "." in filename:
            ext = filename.rsplit(".", 1)[-1].lower()
            if ext.isalnum() and len(ext) <= 10:
                suffix = f".{ext}"
        return f"{prefix.strip('/')}/{uuid.uuid4().hex}{suffix}"

    def upload_fileobj(
        self, fileobj: BinaryIO, key: str, *, content_type: str | None = None
    ) -> str:
        """Upload a file object to S3 under ``key`` and return the key."""
        extra_args: dict[str, str] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        try:
            self._client().upload_fileobj(
                fileobj, self._bucket, key, ExtraArgs=extra_args or None
            )
        except ClientError as exc:
            logger.error("S3 upload failed for key %s: %s", key, exc)
            raise StorageError("Failed to upload object to storage.") from exc
        return key

    def generate_presigned_url(self, key: str, *, expires_in: int | None = None) -> str:
        """Return a time-limited signed URL granting read access to ``key``."""
        if not key:
            return ""
        expires = expires_in or settings.AWS_QUERYSTRING_EXPIRE
        try:
            return self._client().generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires,
            )
        except ClientError as exc:
            logger.error("Presigned URL generation failed for key %s: %s", key, exc)
            raise StorageError("Failed to generate media URL.") from exc

    def delete_object(self, key: str) -> None:
        """Delete an object. Missing objects are treated as already deleted."""
        if not key:
            return
        try:
            self._client().delete_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            # S3 delete is idempotent (a missing key returns success), but guard
            # any other transient error so cleanup jobs can proceed.
            logger.warning("S3 delete encountered an error for key %s: %s", key, exc)
