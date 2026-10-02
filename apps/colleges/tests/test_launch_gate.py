"""Tests for the launch gate on matchmaking and profile edits."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.colleges.models import College
from apps.matchmaking.services.matchmaking_service import MatchmakingService
from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User
from apps.users.services.auth_service import AuthService


def _college(launch_offset_days: float) -> College:
    return College.objects.create(
        code="C_" + uuid.uuid4().hex[:6],
        name="College",
        allowed_email_domains=["c.edu"],
        launch_date=timezone.now() + timedelta(days=launch_offset_days),
    )


def _approved_onboarded(college: College) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@c.edu",
        college=college,
        full_name="Test",
        gender=Gender.MALE,
        intent=Intent.RELATIONSHIP,
        gender_preferences=[Gender.FEMALE],
        onboarding_completed_at=timezone.now(),
        verification_status=VerificationStatus.APPROVED,
    )


class MatchmakingLaunchGateTests(TestCase):
    def test_blocked_before_launch(self) -> None:
        user = _approved_onboarded(_college(3))
        result = MatchmakingService().join(user)
        self.assertTrue(result.failed)
        self.assertEqual(result.error_code, "COLLEGE_NOT_LAUNCHED")

    def test_eligible_after_launch(self) -> None:
        user = _approved_onboarded(_college(-1))
        result = MatchmakingService()._check_eligibility(user)
        self.assertTrue(result.success)


class ProfileLaunchLockTests(TestCase):
    def setUp(self) -> None:
        self.service = AuthService()

    def test_edit_blocked_before_launch_after_onboarding(self) -> None:
        user = _approved_onboarded(_college(3))
        result = self.service.update_profile(user, full_name="New Name")
        self.assertTrue(result.failed)
        self.assertEqual(result.error_code, "COLLEGE_NOT_LAUNCHED")

    def test_edit_allowed_during_onboarding(self) -> None:
        # Pre-launch is fine while the user is still onboarding.
        user = User.objects.create(
            firebase_uid="fb_" + uuid.uuid4().hex,
            college_email=f"{uuid.uuid4().hex}@c.edu",
            college=_college(3),
        )
        result = self.service.update_profile(user, full_name="During Onboarding")
        self.assertTrue(result.success)
        user.refresh_from_db()
        self.assertEqual(user.full_name, "During Onboarding")

    def test_edit_allowed_after_launch(self) -> None:
        user = _approved_onboarded(_college(-1))
        result = self.service.update_profile(user, intent=Intent.FRIENDSHIP)
        self.assertTrue(result.success)
