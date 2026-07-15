"""Tests for VerificationService (storage/notifications/audit mocked)."""

from __future__ import annotations

import io
import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.common.services.storage_service import StorageService
from apps.configuration.services.configuration_service import ConfigurationService
from apps.users.enums import VerificationStatus
from apps.users.models import User
from apps.verification.models import VerificationRequest
from apps.verification.services.verification_service import VerificationService


def _user(**overrides) -> User:
    data = {
        "firebase_uid": "fb_" + uuid.uuid4().hex,
        "college_email": f"{uuid.uuid4().hex}@college.edu",
    }
    data.update(overrides)
    return User.objects.create(**data)


class VerificationServiceTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.storage = mock.MagicMock()
        # Use the real (static) key builder; stub the upload to echo the key.
        self.storage.build_key.side_effect = StorageService.build_key
        self.storage.upload_fileobj.side_effect = (
            lambda fileobj, key, content_type=None: key
        )
        self.notifications = mock.MagicMock()
        self.audit = mock.MagicMock()
        self.service = VerificationService(
            configuration_service=ConfigurationService(),
            storage_service=self.storage,
            notification_service=self.notifications,
            audit_service=self.audit,
        )
        self.user = _user()

    def _complete_draft(self) -> None:
        self.service.generate_gesture(self.user)
        self.service.upload_college_id(
            self.user,
            fileobj=io.BytesIO(b"x"),
            filename="id.jpg",
            content_type="image/jpeg",
        )
        self.service.upload_gesture_selfie(
            self.user,
            fileobj=io.BytesIO(b"x"),
            filename="s.jpg",
            content_type="image/jpeg",
        )

    def test_generate_gesture_creates_draft(self) -> None:
        result = self.service.generate_gesture(self.user)
        self.assertTrue(result.success)
        draft = VerificationRequest.objects.get(user=self.user)
        self.assertEqual(draft.attempt_number, 1)
        self.assertEqual(draft.gesture_type, result.data)

    def test_cannot_start_when_already_approved(self) -> None:
        self.user.verification_status = VerificationStatus.APPROVED
        self.user.save(update_fields=["verification_status"])
        self.assertEqual(
            self.service.generate_gesture(self.user).error_code, "CONFLICT"
        )

    def test_submit_requires_complete_draft(self) -> None:
        self.service.generate_gesture(self.user)  # gesture only, no uploads
        self.assertEqual(self.service.submit(self.user).error_code, "VALIDATION_ERROR")

    def test_submit_without_draft(self) -> None:
        self.assertEqual(self.service.submit(self.user).error_code, "VALIDATION_ERROR")

    def test_full_submit_flow(self) -> None:
        self._complete_draft()
        result = self.service.submit(self.user)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.data.submitted_at)
        self.user.refresh_from_db()
        self.assertEqual(self.user.verification_status, VerificationStatus.PENDING)
        self.assertTrue(self.service.has_submitted_request(self.user))

    def test_resubmission_creates_new_attempt(self) -> None:
        self._complete_draft()
        first = self.service.submit(self.user).data
        self.service.reject(request_id=str(first.id), admin_id="1", notes="blurry")
        self._complete_draft()
        second = self.service.submit(self.user).data
        self.assertEqual(second.attempt_number, 2)
        self.assertNotEqual(first.id, second.id)

    def test_approve_updates_user_and_notifies(self) -> None:
        self._complete_draft()
        request = self.service.submit(self.user).data
        result = self.service.approve(request_id=str(request.id), admin_id="1")
        self.assertTrue(result.success)
        self.user.refresh_from_db()
        self.assertEqual(self.user.verification_status, VerificationStatus.APPROVED)
        self.assertIsNotNone(self.user.verified_at)
        self.notifications.create_notification.assert_called_once()
        self.audit.log.assert_called_once()

    def test_review_rejects_unsubmitted_request(self) -> None:
        self.service.generate_gesture(self.user)
        draft = VerificationRequest.objects.get(user=self.user)
        self.assertEqual(
            self.service.approve(request_id=str(draft.id), admin_id="1").error_code,
            "VALIDATION_ERROR",
        )

    def test_approve_missing_request(self) -> None:
        self.assertEqual(
            self.service.approve(request_id=str(uuid.uuid4()), admin_id="1").error_code,
            "RESOURCE_NOT_FOUND",
        )
