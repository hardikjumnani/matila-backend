"""
Object storage service (Azure Blob Storage).

The application's abstraction over Azure Blob Storage. All uploaded media is
private: containers are not public, and objects are read exclusively through
short-lived SAS (shared access signature) URLs. The Blob service client is
created lazily from the connection string so importing this module performs no
I/O and tests can mock the client.

Storage keys (blob names), not URLs, are what callers persist; access URLs are
minted on demand via :meth:`generate_presigned_url`. Deletion is idempotent.

The public interface (build_key, upload_fileobj, generate_presigned_url,
delete_object) is unchanged from the previous S3 implementation, so callers and
the media-cleanup job are unaffected.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import BinaryIO

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)
from django.conf import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when an object storage operation fails unrecoverably."""


def _parse_connection_string(connection_string: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for segment in connection_string.split(";"):
        if "=" in segment:
            key, value = segment.split("=", 1)
            parts[key.strip()] = value.strip()
    return parts


class StorageService:
    """Upload, sign, and delete private media objects in Azure Blob Storage."""

    def __init__(self) -> None:
        self._service_client: BlobServiceClient | None = None
        self._account_name = ""
        self._account_key = ""

    def _client(self) -> BlobServiceClient:
        if self._service_client is None:
            connection_string = settings.AZURE_STORAGE_CONNECTION_STRING
            if not connection_string:
                raise StorageError("AZURE_STORAGE_CONNECTION_STRING is not configured.")
            self._service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
            parsed = _parse_connection_string(connection_string)
            self._account_name = parsed.get("AccountName", "")
            self._account_key = parsed.get("AccountKey", "")
        return self._service_client

    @property
    def _container(self) -> str:
        container = settings.AZURE_STORAGE_CONTAINER
        if not container:
            raise StorageError("AZURE_STORAGE_CONTAINER is not configured.")
        return container

    @staticmethod
    def build_key(prefix: str, filename: str) -> str:
        """Build a collision-proof blob name: ``<prefix>/<uuid><ext>``.

        The original filename is never trusted for the stored name (only its
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
        """Upload a file object to the container under ``key``; return the key."""
        content_settings = (
            ContentSettings(content_type=content_type) if content_type else None
        )
        try:
            blob = self._client().get_blob_client(container=self._container, blob=key)
            blob.upload_blob(
                fileobj, overwrite=False, content_settings=content_settings
            )
        except AzureError as exc:
            logger.error("Blob upload failed for key %s: %s", key, exc)
            raise StorageError("Failed to upload object to storage.") from exc
        return key

    def generate_presigned_url(self, key: str, *, expires_in: int | None = None) -> str:
        """Return a time-limited SAS URL granting read access to ``key``."""
        if not key:
            return ""
        self._client()  # Ensure the account name/key are parsed.
        expires = expires_in or settings.AZURE_SAS_EXPIRY_SECONDS
        try:
            sas_token = generate_blob_sas(
                account_name=self._account_name,
                container_name=self._container,
                blob_name=key,
                account_key=self._account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(dt_timezone.utc) + timedelta(seconds=expires),
            )
        except Exception as exc:  # noqa: BLE001 — SAS signing can raise various errors.
            logger.error("SAS URL generation failed for key %s: %s", key, exc)
            raise StorageError("Failed to generate media URL.") from exc
        blob_url = (
            self._client().get_blob_client(container=self._container, blob=key).url
        )
        return f"{blob_url}?{sas_token}"

    def delete_object(self, key: str) -> None:
        """Delete a blob. Missing blobs are treated as already deleted."""
        if not key:
            return
        try:
            self._client().get_blob_client(
                container=self._container, blob=key
            ).delete_blob()
        except ResourceNotFoundError:
            pass  # Idempotent: already gone.
        except AzureError as exc:
            logger.warning("Blob delete encountered an error for key %s: %s", key, exc)
