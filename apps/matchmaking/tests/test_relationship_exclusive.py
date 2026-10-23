"""Tests for the relationship-exclusive / multi-chat rule.

One active RELATIONSHIP chat per user; FRIENDSHIP/CASUAL unlimited in parallel.
"""

from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone

from apps.chats.services.chat_service import ChatService
from apps.matchmaking.enums import MatchQueueStatus
from apps.matchmaking.models import MatchQueue
from apps.matchmaking.services.matchmaking_service import MatchmakingService
from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User


def _eligible(intent=Intent.RELATIONSHIP, gender=Gender.OTHER, prefs=None) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        gender=gender,
        intent=intent,
        gender_preferences=prefs if prefs is not None else [],
        verification_status=VerificationStatus.APPROVED,
        onboarding_completed_at=timezone.now(),
    )


class CreateChatIntentTests(TestCase):
    def setUp(self) -> None:
        self.chats = ChatService()

    def test_snapshots_matched_intent(self):
        a, b = _eligible(), _eligible()
        chat = self.chats.create_chat(a, b, intent=Intent.FRIENDSHIP).data
        chat.refresh_from_db()
        self.assertEqual(chat.matched_intent, Intent.FRIENDSHIP)

    def test_defaults_intent_from_user_a(self):
        a, b = _eligible(intent=Intent.CASUAL), _eligible(intent=Intent.CASUAL)
        chat = self.chats.create_chat(a, b).data  # no intent passed
        self.assertEqual(chat.matched_intent, Intent.CASUAL)

    def test_has_open_relationship_chat_only_for_relationship(self):
        a, b = _eligible(), _eligible()
        self.chats.create_chat(a, b, intent=Intent.FRIENDSHIP)
        self.assertFalse(self.chats.has_open_relationship_chat(a))
        c, d = _eligible(), _eligible()
        self.chats.create_chat(c, d, intent=Intent.RELATIONSHIP)
        self.assertTrue(self.chats.has_open_relationship_chat(c))

    def test_relationship_second_chat_conflicts(self):
        a, b, c = _eligible(), _eligible(), _eligible()
        self.assertTrue(self.chats.create_chat(a, b, intent=Intent.RELATIONSHIP).success)
        result = self.chats.create_chat(a, c, intent=Intent.RELATIONSHIP)
        self.assertTrue(result.failed)
        self.assertEqual(result.error_code, "CONFLICT")

    def test_friendship_chats_run_in_parallel(self):
        a, b, c = _eligible(), _eligible(), _eligible()
        self.assertTrue(self.chats.create_chat(a, b, intent=Intent.FRIENDSHIP).success)
        self.assertTrue(self.chats.create_chat(a, c, intent=Intent.FRIENDSHIP).success)

    def test_relationship_chat_does_not_block_a_friendship_chat(self):
        a, b, c = _eligible(), _eligible(), _eligible()
        self.chats.create_chat(a, b, intent=Intent.RELATIONSHIP)
        self.assertTrue(self.chats.create_chat(a, c, intent=Intent.FRIENDSHIP).success)

    def test_active_chat_ids_lists_all(self):
        a, b, c = _eligible(), _eligible(), _eligible()
        self.chats.create_chat(a, b, intent=Intent.FRIENDSHIP)
        self.chats.create_chat(a, c, intent=Intent.FRIENDSHIP)
        self.assertEqual(len(self.chats.active_chat_ids(a)), 2)


class JoinGuardTests(TestCase):
    def setUp(self) -> None:
        self.chats = ChatService()
        self.svc = MatchmakingService()

    def test_relationship_join_blocked_with_open_relationship_chat(self):
        a, b = _eligible(Intent.RELATIONSHIP), _eligible(Intent.RELATIONSHIP)
        self.chats.create_chat(a, b, intent=Intent.RELATIONSHIP)
        result = self.svc.join(a)
        self.assertTrue(result.failed)
        self.assertEqual(result.error_code, "CONFLICT")

    def test_friendship_join_not_blocked_with_open_friendship_chat(self):
        a = _eligible(Intent.FRIENDSHIP)
        b = _eligible(Intent.FRIENDSHIP)
        self.chats.create_chat(a, b, intent=Intent.FRIENDSHIP)
        result = self.svc.join(a)  # no other searcher -> queues, not CONFLICT
        self.assertTrue(result.success)
        self.assertFalse(result.data.matched)

    def test_relationship_join_allowed_with_only_a_friendship_chat(self):
        a = _eligible(Intent.RELATIONSHIP)
        b = _eligible(Intent.FRIENDSHIP)
        self.chats.create_chat(a, b, intent=Intent.FRIENDSHIP)
        result = self.svc.join(a)
        self.assertTrue(result.success)


class StatusOrderingTests(TestCase):
    def setUp(self) -> None:
        self.chats = ChatService()
        self.svc = MatchmakingService()

    def test_searching_takes_precedence_over_open_chat(self):
        a = _eligible(Intent.FRIENDSHIP)
        b = _eligible(Intent.FRIENDSHIP)
        self.chats.create_chat(a, b, intent=Intent.FRIENDSHIP)
        MatchQueue.objects.create(
            user=a, intent=a.intent, gender_preferences=[],
            is_online=True, last_heartbeat_at=timezone.now(),
            status=MatchQueueStatus.SEARCHING,
        )
        self.assertEqual(self.svc.get_status(a)["state"], "SEARCHING")

    def test_matched_when_open_chat_and_not_searching(self):
        a = _eligible(Intent.FRIENDSHIP)
        b = _eligible(Intent.FRIENDSHIP)
        chat = self.chats.create_chat(a, b, intent=Intent.FRIENDSHIP).data
        status = self.svc.get_status(a)
        self.assertEqual(status["state"], "MATCHED")
        self.assertEqual(status["chat_id"], str(chat.id))
