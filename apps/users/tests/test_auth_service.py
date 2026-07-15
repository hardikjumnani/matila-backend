"""Tests for AuthService session bootstrap and next-action derivation."""

from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone

from apps.users.enums import AccountStatus, NextAction, VerificationStatus
from apps.users.models import User
from apps.users.services.auth_service import AuthService
from apps.verification.models import VerificationRequest


class BootstrapSessionTests(TestCase):
    def setUp(self) -> None:
        self.service = AuthService()
        self.uid = "fb_" + uuid.uuid4().hex
        self.email = f"{uuid.uuid4().hex}@college.edu"

    def test_creates_user_on_first_bootstrap(self) -> None:
        result = self.service.bootstrap_session(firebase_uid=self.uid, email=self.email)
        self.assertTrue(result.success)
        self.assertTrue(result.data.created)
        self.assertEqual(result.data.user.college_email, self.email)
        self.assertEqual(result.data.next_action, NextAction.COMPLETE_ONBOARDING)
        self.assertIsNotNone(result.data.user.last_active_at)

    def test_fetches_existing_user_without_recreating(self) -> None:
        self.service.bootstrap_session(firebase_uid=self.uid, email=self.email)
        result = self.service.bootstrap_session(firebase_uid=self.uid, email=self.email)
        self.assertTrue(result.success)
        self.assertFalse(result.data.created)
        self.assertEqual(User.objects.filter(firebase_uid=self.uid).count(), 1)

    def test_missing_email_is_rejected(self) -> None:
        result = self.service.bootstrap_session(firebase_uid=self.uid, email="")
        self.assertTrue(result.failed)
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_suspended_account_is_denied(self) -> None:
        User.objects.create(
            firebase_uid=self.uid,
            college_email=self.email,
            account_status=AccountStatus.SUSPENDED,
        )
        result = self.service.bootstrap_session(firebase_uid=self.uid, email=self.email)
        self.assertEqual(result.error_code, "ACCOUNT_SUSPENDED")

    def test_banned_account_is_denied(self) -> None:
        User.objects.create(
            firebase_uid=self.uid,
            college_email=self.email,
            account_status=AccountStatus.BANNED,
        )
        result = self.service.bootstrap_session(firebase_uid=self.uid, email=self.email)
        self.assertEqual(result.error_code, "ACCOUNT_BANNED")


class NextActionTests(TestCase):
    def setUp(self) -> None:
        self.service = AuthService()

    def _user(self, **overrides) -> User:
        data = {
            "firebase_uid": "fb_" + uuid.uuid4().hex,
            "college_email": f"{uuid.uuid4().hex}@college.edu",
        }
        data.update(overrides)
        return User.objects.create(**data)

    def test_incomplete_onboarding(self) -> None:
        user = self._user()
        self.assertEqual(
            self.service._determine_next_action(user), NextAction.COMPLETE_ONBOARDING
        )

    def test_approved_goes_home(self) -> None:
        user = self._user(
            onboarding_completed_at=timezone.now(),
            verification_status=VerificationStatus.APPROVED,
        )
        self.assertEqual(self.service._determine_next_action(user), NextAction.GO_HOME)

    def test_rejected_resubmits(self) -> None:
        user = self._user(
            onboarding_completed_at=timezone.now(),
            verification_status=VerificationStatus.REJECTED,
        )
        self.assertEqual(
            self.service._determine_next_action(user), NextAction.SUBMIT_VERIFICATION
        )

    def test_pending_without_submission_submits(self) -> None:
        user = self._user(onboarding_completed_at=timezone.now())
        self.assertEqual(
            self.service._determine_next_action(user), NextAction.SUBMIT_VERIFICATION
        )

    def test_pending_with_submission_waits(self) -> None:
        user = self._user(onboarding_completed_at=timezone.now())
        VerificationRequest.objects.create(
            user=user, attempt_number=1, submitted_at=timezone.now()
        )
        self.assertEqual(
            self.service._determine_next_action(user), NextAction.WAIT_FOR_VERIFICATION
        )
