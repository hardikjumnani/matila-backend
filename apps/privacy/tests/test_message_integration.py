"""Integration: Veil blocks leaks through the real MessageService.send_text."""

from __future__ import annotations

import uuid

from django.core.cache import cache
from django.test import TestCase

from apps.chats.enums import ChatPhase, ChatStatus
from apps.chats.models import Chat, ChatParticipant
from apps.messaging.models import Message
from apps.messaging.services.message_service import MessageService
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class SendTextVeilIntegrationTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.a = _user()
        self.b = _user()
        self.chat = Chat.objects.create(
            status=ChatStatus.ACTIVE, current_phase=ChatPhase.ANONYMOUS
        )
        ChatParticipant.objects.create(chat=self.chat, user=self.a)
        ChatParticipant.objects.create(chat=self.chat, user=self.b)
        self.ms = MessageService()

    def test_blocks_phone_number(self):
        res = self.ms.send_text(
            chat_id=str(self.chat.id), sender=self.a, content="call me 9876543210"
        )
        self.assertTrue(res.failed)
        self.assertEqual(res.error_code, "MESSAGE_BLOCKED")
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())

    def test_allows_benign_message(self):
        res = self.ms.send_text(
            chat_id=str(self.chat.id), sender=self.a, content="hey how are you"
        )
        self.assertTrue(res.success)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 1)

    def test_masks_profanity_but_sends(self):
        res = self.ms.send_text(
            chat_id=str(self.chat.id), sender=self.a, content="you motherfucker"
        )
        self.assertTrue(res.success)  # Muffle masks, does NOT block
        self.assertIn("*", res.data.text_content)
        self.assertNotIn("motherfucker", res.data.text_content)

    def test_casual_profanity_sent_as_is(self):
        res = self.ms.send_text(
            chat_id=str(self.chat.id), sender=self.a, content="this is fucking great"
        )
        self.assertTrue(res.success)
        self.assertEqual(res.data.text_content, "this is fucking great")

    def test_disengages_after_reveal(self):
        # Once the chat is REVEALED, sharing contact details is fine.
        self.chat.current_phase = ChatPhase.REVEALED
        self.chat.status = ChatStatus.REVEALED
        self.chat.save(update_fields=["current_phase", "status"])
        res = self.ms.send_text(
            chat_id=str(self.chat.id), sender=self.a, content="my number is 9876543210"
        )
        self.assertTrue(res.success)
