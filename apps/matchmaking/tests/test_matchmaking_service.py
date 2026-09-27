"""Tests for MatchmakingService (notifications mocked; real ChatService)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.chats.services.chat_service import ChatService
from apps.matchmaking.enums import MatchQueueStatus
from apps.matchmaking.models import MatchQueue
from apps.matchmaking.services.matchmaking_service import MatchmakingService
from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User


def _eligible(gender: str, intent: str, prefs: list[str]) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        gender=gender,
        intent=intent,
        gender_preferences=prefs,
        verification_status=VerificationStatus.APPROVED,
        onboarding_completed_at=timezone.now(),
    )


class MatchmakingServiceTests(TestCase):
    def setUp(self) -> None:
        self.notifications = mock.MagicMock()
        chat_service = ChatService(notification_service=mock.MagicMock())
        self.service = MatchmakingService(
            chat_service=chat_service, notification_service=self.notifications
        )

    def test_unverified_user_cannot_join(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        user.verification_status = VerificationStatus.PENDING
        user.save(update_fields=["verification_status"])
        self.assertEqual(self.service.join(user).error_code, "VERIFICATION_REQUIRED")

    def test_join_without_partner_queues(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        result = self.service.join(user)
        self.assertTrue(result.success)
        self.assertFalse(result.data.matched)
        self.assertEqual(
            MatchQueue.objects.filter(
                user=user, status=MatchQueueStatus.SEARCHING
            ).count(),
            1,
        )

    def test_join_is_idempotent(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        self.service.join(user)
        self.service.join(user)
        self.assertEqual(
            MatchQueue.objects.filter(
                user=user, status=MatchQueueStatus.SEARCHING
            ).count(),
            1,
        )

    def test_compatible_users_match(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self.service.join(a)
        result = self.service.join(b)
        self.assertTrue(result.data.matched)
        self.assertIsNotNone(result.data.chat)
        # Both queue entries removed on match.
        self.assertEqual(
            MatchQueue.objects.filter(status=MatchQueueStatus.SEARCHING).count(), 0
        )
        # Both users notified.
        self.assertEqual(self.notifications.create_notification.call_count, 2)

    def test_incompatible_gender_preference_does_not_match(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.MALE])  # wants MALE
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self.service.join(a)
        result = self.service.join(b)
        self.assertFalse(result.data.matched)

    def test_different_intent_does_not_match(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.CASUAL, [Gender.MALE])
        self.service.join(a)
        self.assertFalse(self.service.join(b).data.matched)

    def test_empty_preferences_match_any_gender(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [])
        self.service.join(a)
        self.assertTrue(self.service.join(b).data.matched)

    def test_cannot_join_with_active_chat(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        self.service.join(a)
        self.service.join(b)  # a and b now in a chat
        self.assertEqual(self.service.join(a).error_code, "CONFLICT")

    def test_leave_cancels_entry(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        self.service.join(user)
        self.service.leave(user)
        self.assertFalse(
            MatchQueue.objects.filter(
                user=user, status=MatchQueueStatus.SEARCHING
            ).exists()
        )

    def test_status_transitions(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        self.assertEqual(self.service.get_status(user)["state"], "IDLE")
        self.service.join(user)
        self.assertEqual(self.service.get_status(user)["state"], "SEARCHING")

    def test_heartbeat_without_entry_fails(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        self.assertEqual(self.service.heartbeat(user).error_code, "RESOURCE_NOT_FOUND")

    def test_cleanup_stale_times_out_entries(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        self.service.join(user)
        MatchQueue.objects.filter(user=user).update(
            last_heartbeat_at=timezone.now() - timedelta(minutes=30)
        )
        removed = self.service.cleanup_stale(timeout_seconds=300)
        self.assertEqual(removed, 1)
        entry = MatchQueue.objects.get(user=user)
        self.assertEqual(entry.status, MatchQueueStatus.TIMEOUT)

    def test_active_user_range_is_bucketed(self) -> None:
        for _ in range(3):
            self.service.join(_eligible(Gender.MALE, Intent.CASUAL, [Gender.MALE]))
        rng = self.service.get_active_user_range()
        self.assertEqual(rng["min"], 0)
        self.assertEqual(rng["max"], 10)
