"""API tests for the users/me endpoints and the response envelope."""

from __future__ import annotations

import uuid
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User

_ME = "/api/v1/users/me"


def _user(**overrides) -> User:
    data = {
        "firebase_uid": "fb_" + uuid.uuid4().hex,
        "college_email": f"{uuid.uuid4().hex}@college.edu",
    }
    data.update(overrides)
    return User.objects.create(**data)


class MeEndpointTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = _user()
        self.client.force_authenticate(user=self.user)

    def test_get_me_wrapped_in_success_envelope(self) -> None:
        response = self.client.get(_ME)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["id"], str(self.user.id))
        self.assertIsNone(body["message"])

    def test_unauthenticated_returns_error_envelope(self) -> None:
        response = APIClient().get(_ME)
        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "UNAUTHORIZED")

    def test_patch_updates_full_name(self) -> None:
        response = self.client.patch(_ME, {"full_name": "Alice"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Alice")

    def test_patch_gender_after_verification_conflicts(self) -> None:
        self.user.verification_status = VerificationStatus.APPROVED
        self.user.save(update_fields=["verification_status"])
        response = self.client.patch(_ME, {"gender": Gender.FEMALE}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "CONFLICT")

    def test_patch_empty_is_validation_error(self) -> None:
        response = self.client.patch(_ME, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_patch_invalid_choice_is_validation_error(self) -> None:
        response = self.client.patch(_ME, {"gender": "ALIEN"}, format="json")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("details", body["error"])

    def test_complete_onboarding_incomplete(self) -> None:
        response = self.client.post(_ME + "/complete-onboarding")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_complete_onboarding_success(self) -> None:
        self.user.full_name = "Alice"
        self.user.gender = Gender.FEMALE
        self.user.intent = Intent.RELATIONSHIP
        self.user.gender_preferences = [Gender.MALE]
        self.user.save()
        response = self.client.post(_ME + "/complete-onboarding")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.onboarding_completed_at)

    def test_profile_photo_upload(self) -> None:
        upload = SimpleUploadedFile("p.jpg", b"data", content_type="image/jpeg")
        with mock.patch(
            "apps.common.services.storage_service.StorageService.upload_fileobj",
            return_value="profile-photos/x.jpg",
        ):
            response = self.client.post(
                _ME + "/profile-photo", {"file": upload}, format="multipart"
            )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile_photo_url)

    def test_profile_photo_rejects_non_image(self) -> None:
        upload = SimpleUploadedFile("p.txt", b"data", content_type="text/plain")
        response = self.client.post(
            _ME + "/profile-photo", {"file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, 400)
