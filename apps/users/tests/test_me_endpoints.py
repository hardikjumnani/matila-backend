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
        from datetime import date

        self.user.full_name = "Alice"
        self.user.gender = Gender.FEMALE
        self.user.intent = Intent.RELATIONSHIP
        self.user.gender_preferences = [Gender.MALE]
        self.user.date_of_birth = date(2000, 1, 1)
        self.user.save()
        response = self.client.post(_ME + "/complete-onboarding")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.onboarding_completed_at)

    # -- Date of birth + age preference ------------------------------------

    def test_patch_sets_dob_during_onboarding_and_exposes_age(self) -> None:
        from datetime import date

        response = self.client.patch(
            _ME, {"date_of_birth": "2000-05-20"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.date_of_birth, date(2000, 5, 20))
        data = response.json()["data"]
        self.assertEqual(data["date_of_birth"], "2000-05-20")
        self.assertIsNotNone(data["age"])

    def test_patch_dob_underage_rejected(self) -> None:
        from datetime import date

        today = date.today()
        underage = date(today.year - 16, today.month, today.day).isoformat()
        response = self.client.patch(
            _ME, {"date_of_birth": underage}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_dob_not_editable_after_onboarding(self) -> None:
        from django.utils import timezone

        self.user.onboarding_completed_at = timezone.now()
        self.user.save(update_fields=["onboarding_completed_at"])
        response = self.client.patch(
            _ME, {"date_of_birth": "2000-01-01"}, format="json"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "CONFLICT")

    def test_dob_re_editable_during_resubmission_reonboarding(self) -> None:
        # Resubmission clears onboarding_completed_at, which re-opens DOB editing
        # for the re-onboarding pass; a previously-set DOB can be changed, and it
        # re-locks once onboarding completes again.
        from datetime import date

        from django.utils import timezone

        self.user.date_of_birth = date(2000, 1, 1)
        self.user.onboarding_completed_at = timezone.now()
        self.user.save(update_fields=["date_of_birth", "onboarding_completed_at"])
        # What request_resubmission does: clear onboarding_completed_at.
        self.user.onboarding_completed_at = None
        self.user.save(update_fields=["onboarding_completed_at"])
        response = self.client.patch(
            _ME, {"date_of_birth": "2001-03-04"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.date_of_birth, date(2001, 3, 4))

    def test_age_preference_enable_requires_both_bounds(self) -> None:
        response = self.client.patch(
            _ME, {"age_preference_enabled": True}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_age_preference_set_and_exposed(self) -> None:
        response = self.client.patch(
            _ME,
            {
                "age_preference_enabled": True,
                "age_preference_min": 18,
                "age_preference_max": 22,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["age_preference_enabled"])
        self.assertEqual(data["age_preference_min"], 18)
        self.assertEqual(data["age_preference_max"], 22)

    def test_age_preference_out_of_bounds_rejected(self) -> None:
        response = self.client.patch(
            _ME,
            {
                "age_preference_enabled": True,
                "age_preference_min": 18,
                "age_preference_max": 40,  # > MAX_AGE (30)
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_age_preference_min_greater_than_max_rejected(self) -> None:
        response = self.client.patch(
            _ME,
            {
                "age_preference_enabled": True,
                "age_preference_min": 25,
                "age_preference_max": 20,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

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
