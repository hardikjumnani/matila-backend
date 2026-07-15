"""Tests for StorageService (S3 client mocked; no live AWS)."""

from __future__ import annotations

import io
from unittest import mock

from botocore.exceptions import ClientError
from django.test import TestCase, override_settings

from apps.common.services.storage_service import StorageService

_SETTINGS = {
    "AWS_STORAGE_BUCKET_NAME": "test-bucket",
    "AWS_S3_REGION_NAME": "ap-south-1",
    "AWS_QUERYSTRING_EXPIRE": 3600,
}


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
        self.client = mock.MagicMock()
        self.service._s3 = self.client  # Inject the mocked boto3 client.

    def test_upload_fileobj_calls_s3_and_returns_key(self) -> None:
        result = self.service.upload_fileobj(
            io.BytesIO(b"data"), "chat/abc.jpg", content_type="image/jpeg"
        )
        self.assertEqual(result, "chat/abc.jpg")
        self.client.upload_fileobj.assert_called_once()

    def test_generate_presigned_url_returns_signed_url(self) -> None:
        self.client.generate_presigned_url.return_value = "https://signed"
        self.assertEqual(
            self.service.generate_presigned_url("chat/abc.jpg"), "https://signed"
        )

    def test_delete_object_is_idempotent_on_error(self) -> None:
        self.client.delete_object.side_effect = ClientError({}, "DeleteObject")
        # Must not raise even if S3 reports an error.
        self.service.delete_object("chat/missing.jpg")
        self.client.delete_object.assert_called_once()

    def test_empty_key_is_a_noop(self) -> None:
        self.assertEqual(self.service.generate_presigned_url(""), "")
        self.service.delete_object("")
        self.client.delete_object.assert_not_called()
