"""Demo/review-account isolation in matchmaking (AI_BRIDGE [00079]).

A demo account matches ONLY with other demo accounts and never inflates the
real population used for lobby/intent social proof.
"""

from __future__ import annotations

import uuid
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.chats.services.chat_service import ChatService
from apps.matchmaking.services.matchmaking_service import MatchmakingService
from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User


class DemoIsolationTests(TestCase):
    def setUp(self) -> None:
        self.service = MatchmakingService(
            chat_service=ChatService(notification_service=mock.MagicMock()),
            notification_service=mock.MagicMock(),
        )

    def _user(self, *, is_demo: bool) -> User:
        return User.objects.create(
            firebase_uid="fb_" + uuid.uuid4().hex,
            college_email=f"{uuid.uuid4().hex}@college.edu",
            gender=Gender.OTHER,
            intent=Intent.FRIENDSHIP,
            gender_preferences=[],  # any gender
            verification_status=VerificationStatus.APPROVED,
            onboarding_completed_at=timezone.now(),
            is_demo=is_demo,
        )

    def test_demo_does_not_match_a_waiting_real_user(self) -> None:
        real = self._user(is_demo=False)
        demo = self._user(is_demo=True)
        self.service.join(real)  # real is now waiting
        result = self.service.join(demo)
        self.assertFalse(result.data.matched)

    def test_real_does_not_match_a_waiting_demo_user(self) -> None:
        demo = self._user(is_demo=True)
        real = self._user(is_demo=False)
        self.service.join(demo)  # demo is now waiting
        result = self.service.join(real)
        self.assertFalse(result.data.matched)

    def test_demo_matches_another_demo(self) -> None:
        d1 = self._user(is_demo=True)
        d2 = self._user(is_demo=True)
        self.service.join(d1)
        result = self.service.join(d2)
        self.assertTrue(result.data.matched)
        self.assertIsNotNone(result.data.chat)

    def test_eligible_population_excludes_demo(self) -> None:
        real = self._user(is_demo=False)
        demo = self._user(is_demo=True)
        ids = set(self.service._eligible_users().values_list("id", flat=True))
        self.assertIn(real.id, ids)
        self.assertNotIn(demo.id, ids)
