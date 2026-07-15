"""API tests for the verification endpoints (storage mocked)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.users.enums import VerificationStatus
from apps.users.models import User

_UPLOAD_PATCH = "apps.common.services.storage_service.StorageService.upload_fileobj"


def _onboarded_user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        full_name="Alice",
        onboarding_completed_at=timezone.now(),
    )


class VerificationApiTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.client = APIClient()
        self.user = _onboarded_user()
        self.client.force_authenticate(user=self.user)

    def _image(self, name="p.jpg"):
        return SimpleUploadedFile(name, b"data", content_type="image/jpeg")

    def _complete_uploads(self) -> None:
        self.client.get("/api/v1/verification/gesture")
        with mock.patch(_UPLOAD_PATCH, side_effect=lambda f, k, content_type=None: k):
            self.client.post(
                "/api/v1/verification/upload-college-id",
                {"file": self._image()},
                format="multipart",
            )
            self.client.post(
                "/api/v1/verification/upload-gesture-selfie",
                {"file": self._image()},
                format="multipart",
            )

    def test_requires_onboarding(self) -> None:
        user = User.objects.create(
            firebase_uid="fb_" + uuid.uuid4().hex,
            college_email=f"{uuid.uuid4().hex}@college.edu",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/v1/verification/status")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "ONBOARDING_INCOMPLETE")

    def test_gesture_returns_instruction(self) -> None:
        response = self.client.get("/api/v1/verification/gesture")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["gesture"])

    def test_upload_sets_progress_flag(self) -> None:
        self.client.get("/api/v1/verification/gesture")
        with mock.patch(_UPLOAD_PATCH, side_effect=lambda f, k, content_type=None: k):
            response = self.client.post(
                "/api/v1/verification/upload-college-id",
                {"file": self._image()},
                format="multipart",
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["college_id_uploaded"])

    def test_submit_incomplete_is_validation_error(self) -> None:
        self.client.get("/api/v1/verification/gesture")
        response = self.client.post("/api/v1/verification/submit")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_full_flow(self) -> None:
        self._complete_uploads()
        response = self.client.post("/api/v1/verification/submit")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.verification_status, VerificationStatus.PENDING)

    def test_status_and_history(self) -> None:
        self._complete_uploads()
        self.client.post("/api/v1/verification/submit")
        status = self.client.get("/api/v1/verification/status")
        self.assertEqual(
            status.json()["data"]["verification_status"], VerificationStatus.PENDING
        )
        history = self.client.get("/api/v1/verification/history")
        self.assertEqual(len(history.json()["data"]), 1)

    def test_upload_rejects_non_image(self) -> None:
        self.client.get("/api/v1/verification/gesture")
        bad = SimpleUploadedFile("x.txt", b"data", content_type="text/plain")
        response = self.client.post(
            "/api/v1/verification/upload-college-id",
            {"file": bad},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
