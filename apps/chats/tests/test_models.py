"""Model tests for the chats domain."""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.chats.enums import ChatPhase, ChatStatus
from apps.chats.models import Chat, ChatParticipant
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class ChatModelTests(TestCase):
    def test_chat_defaults(self) -> None:
        chat = Chat.objects.create()
        self.assertIsInstance(chat.id, uuid.UUID)
        self.assertEqual(chat.status, ChatStatus.ACTIVE)
        self.assertEqual(chat.current_phase, ChatPhase.ANONYMOUS)
        self.assertEqual(chat.message_count, 0)
        self.assertEqual(chat.anonymous_chat_extension_count, 0)


class ChatParticipantModelTests(TestCase):
    def test_unique_participant_per_chat_user(self) -> None:
        chat = Chat.objects.create()
        user = _user()
        ChatParticipant.objects.create(chat=chat, user=user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ChatParticipant.objects.create(chat=chat, user=user)

    def test_same_user_can_join_different_chats(self) -> None:
        user = _user()
        p1 = ChatParticipant.objects.create(chat=Chat.objects.create(), user=user)
        p2 = ChatParticipant.objects.create(chat=Chat.objects.create(), user=user)
        self.assertNotEqual(p1.chat_id, p2.chat_id)
