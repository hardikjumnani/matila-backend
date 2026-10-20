"""Tests for VerificationService (storage/notifications/audit mocked)."""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from apps.colleges.models import College
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
        # result.data is now the resolved {code, label, emoji}; the stored
        # gesture_type is the code.
        self.assertEqual(draft.gesture_type, result.data["code"])
        self.assertTrue(result.data["label"])
        self.assertTrue(result.data["emoji"])

    def test_generate_gesture_is_stable_within_attempt(self) -> None:
        # Two requests on the same in-progress draft must return the same gesture
        # and must not re-roll (a re-roll would strand a selfie already taken for
        # the previous gesture).
        fixed = {"code": "THUMBS_UP", "label": "Thumbs up", "emoji": "\U0001f44d"}
        with mock.patch(
            "apps.verification.services.verification_service.secrets.choice",
            return_value=fixed,
        ) as choice:
            first = self.service.generate_gesture(self.user)
            second = self.service.generate_gesture(self.user)
        self.assertTrue(first.success and second.success)
        self.assertEqual(first.data["code"], "THUMBS_UP")
        self.assertEqual(second.data["code"], "THUMBS_UP")
        self.assertEqual(choice.call_count, 1)  # rolled once, not re-rolled
        self.assertEqual(
            VerificationRequest.objects.filter(user=self.user).count(), 1
        )

    def test_new_attempt_assigns_fresh_gesture(self) -> None:
        # A resubmission opens a new draft, which gets its own assigned gesture.
        submitted = self._submitted()
        self.service.request_resubmission(request_id=str(submitted.id), admin_id="1")
        self.user.refresh_from_db()
        result = self.service.generate_gesture(self.user)
        self.assertTrue(result.success)
        draft2 = self.service.get_latest_request(self.user)
        self.assertEqual(draft2.attempt_number, 2)
        self.assertIsNone(draft2.submitted_at)
        self.assertTrue(draft2.gesture_type)
        self.assertEqual(draft2.gesture_type, result.data["code"])

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

    def test_approve_prelaunch_message_mentions_countdown(self) -> None:
        # Approval during the pre-launch window points the user at the countdown.
        self._complete_draft()
        request = self.service.submit(self.user).data
        self.user.college = College.objects.create(
            code="FUT",
            name="Future U",
            allowed_email_domains=["fut.edu"],
            launch_date=timezone.now() + timedelta(days=5),
        )
        self.user.save(update_fields=["college"])
        self.service.approve(request_id=str(request.id), admin_id="1")
        body = self.notifications.create_notification.call_args.kwargs["body"]
        self.assertIn("countdown", body.lower())

    def _submitted(self):
        self._complete_draft()
        return self.service.submit(self.user).data

    def test_approve_sets_action_type(self) -> None:
        self.service.approve(request_id=str(self._submitted().id), admin_id="1")
        kwargs = self.notifications.create_notification.call_args.kwargs
        self.assertEqual(kwargs["action_type"], "VERIFICATION_APPROVED")

    def test_reject_notification_carries_note_and_action_type(self) -> None:
        self.service.reject(
            request_id=str(self._submitted().id), admin_id="1", notes="ID is blurry"
        )
        kwargs = self.notifications.create_notification.call_args.kwargs
        self.assertEqual(kwargs["action_type"], "VERIFICATION_REJECTED")
        self.assertEqual(kwargs["body"], "ID is blurry")

    def test_reject_empty_note_uses_generic_body(self) -> None:
        self.service.reject(
            request_id=str(self._submitted().id), admin_id="1", notes=""
        )
        kwargs = self.notifications.create_notification.call_args.kwargs
        self.assertEqual(kwargs["action_type"], "VERIFICATION_REJECTED")
        self.assertTrue(kwargs["body"])  # generic fallback

    def test_resubmission_notification_carries_note_and_action_type(self) -> None:
        self.service.request_resubmission(
            request_id=str(self._submitted().id),
            admin_id="1",
            notes="Re-upload your selfie",
        )
        kwargs = self.notifications.create_notification.call_args.kwargs
        self.assertEqual(kwargs["action_type"], "VERIFICATION_RESUBMISSION_REQUIRED")
        self.assertEqual(kwargs["body"], "Re-upload your selfie")

    def test_status_review_message_on_resubmission(self) -> None:
        request = self._submitted()
        self.service.request_resubmission(
            request_id=str(request.id), admin_id="1", notes="Re-upload your ID"
        )
        self.user.refresh_from_db()
        status = self.service.get_status(self.user)
        self.assertEqual(
            status["verification_status"], VerificationStatus.RESUBMISSION_REQUIRED
        )
        self.assertEqual(status["review_message"], "Re-upload your ID")

    def test_status_no_review_message_when_pending(self) -> None:
        self._submitted()
        self.user.refresh_from_db()
        status = self.service.get_status(self.user)
        self.assertEqual(status["review_message"], "")

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
