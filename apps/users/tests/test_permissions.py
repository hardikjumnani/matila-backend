"""Tests for the onboarding/verification permission classes."""

from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from apps.users.enums import VerificationStatus
from apps.users.models import User
from apps.users.permissions import IsOnboardingCompleted, IsVerifiedUser


class PermissionTests(TestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()

    def _user(self, **overrides) -> User:
        data = {
            "firebase_uid": "fb_" + uuid.uuid4().hex,
            "college_email": f"{uuid.uuid4().hex}@college.edu",
        }
        data.update(overrides)
        return User.objects.create(**data)

    def _request(self, user):
        request = self.factory.get("/")
        request.user = user
        return request

    def test_onboarding_required(self) -> None:
        perm = IsOnboardingCompleted()
        self.assertFalse(perm.has_permission(self._request(self._user()), None))
        onboarded = self._user(onboarding_completed_at=timezone.now())
        self.assertTrue(perm.has_permission(self._request(onboarded), None))

    def test_verification_required(self) -> None:
        perm = IsVerifiedUser()
        self.assertFalse(perm.has_permission(self._request(self._user()), None))
        verified = self._user(verification_status=VerificationStatus.APPROVED)
        self.assertTrue(perm.has_permission(self._request(verified), None))

    def test_anonymous_denied(self) -> None:
        self.assertFalse(IsVerifiedUser().has_permission(self._request(None), None))
        self.assertFalse(
            IsOnboardingCompleted().has_permission(self._request(None), None)
        )
