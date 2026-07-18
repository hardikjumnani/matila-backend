"""Tests for StorageService (Azure Blob client mocked; no live Azure)."""

from __future__ import annotations

import io
from unittest import mock

from azure.core.exceptions import AzureError, ResourceNotFoundError
from django.test import TestCase, override_settings

from apps.common.services.storage_service import StorageService

_SETTINGS = {
    "AZURE_STORAGE_CONNECTION_STRING": (
        "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=a2V5;"
        "EndpointSuffix=core.windows.net"
    ),
    "AZURE_STORAGE_CONTAINER": "media",
    "AZURE_SAS_EXPIRY_SECONDS": 3600,
}
_SAS = "apps.common.services.storage_service.generate_blob_sas"


class BuildKeyTests(TestCase):
    def test_key_uses_prefix_and_preserves_extension(self) -> None:
        key = StorageService.build_key("verification/college-id", "scan.JPG")
        self.assertTrue(key.startswith("verification/college-id/"))
        self.assertTrue(key.endswith(".jpg"))

    def test_key_ignores_untrusted_filename_body(self) -> None:
        key = StorageService.build_key("chat", "../../etc/passwd")
        self.assertTrue(key.startswith("chat/"))
        self.assertNotIn("..", key)


@override_settings(**_SETTINGS)
class StorageOperationTests(TestCase):
    def setUp(self) -> None:
        self.service = StorageService()
        self.blob = mock.MagicMock()
        # Inject a mocked Blob service client and skip connection-string parsing.
        self.service._service_client = mock.MagicMock()
        self.service._service_client.get_blob_client.return_value = self.blob
        self.service._account_name = "acct"
        self.service._account_key = "a2V5"

    def test_upload_calls_blob_and_returns_key(self) -> None:
        result = self.service.upload_fileobj(
            io.BytesIO(b"data"), "chat/abc.jpg", content_type="image/jpeg"
        )
        self.assertEqual(result, "chat/abc.jpg")
        self.blob.upload_blob.assert_called_once()

    def test_generate_presigned_url_returns_sas_url(self) -> None:
        self.blob.url = "https://acct.blob.core.windows.net/media/chat/abc.jpg"
        with mock.patch(_SAS, return_value="sig=abc"):
            url = self.service.generate_presigned_url("chat/abc.jpg")
        self.assertEqual(url, self.blob.url + "?sig=abc")

    def test_delete_is_idempotent_when_missing(self) -> None:
        self.blob.delete_blob.side_effect = ResourceNotFoundError("gone")
        self.service.delete_object("chat/missing.jpg")  # Must not raise.
        self.blob.delete_blob.assert_called_once()

    def test_delete_swallows_other_azure_errors(self) -> None:
        self.blob.delete_blob.side_effect = AzureError("transient")
        self.service.delete_object("chat/x.jpg")  # Must not raise.

    def test_empty_key_is_a_noop(self) -> None:
        self.assertEqual(self.service.generate_presigned_url(""), "")
        self.service.delete_object("")
        self.service._service_client.get_blob_client.assert_not_called()
