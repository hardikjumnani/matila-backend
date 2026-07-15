"""Tests for ChatService read-receipt pointer."""

from __future__ import annotations

import uuid
from unittest import mock

from django.test import TestCase

from apps.chats.services.chat_service import ChatService
from apps.messaging.enums import MessageType
from apps.messaging.models import Message
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class MarkReadTests(TestCase):
    def setUp(self) -> None:
        self.service = ChatService(notification_service=mock.MagicMock())
        self.a = _user()
        self.b = _user()
        self.chat = self.service.create_chat(self.a, self.b).data
        self.message = Message.objects.create(
            chat=self.chat,
            sender=self.a,
            message_type=MessageType.TEXT,
            text_content="hi",
        )

    def test_mark_read_advances_pointer(self) -> None:
        result = self.service.mark_read(
            user=self.b,
            chat_id=str(self.chat.id),
            last_read_message_id=str(self.message.id),
        )
        self.assertTrue(result.success)
        result.data.refresh_from_db()
        self.assertEqual(result.data.last_read_message_id, self.message.id)
        self.assertIsNotNone(result.data.last_read_at)

    def test_message_from_another_chat_rejected(self) -> None:
        other_chat = self.service.create_chat(_user(), _user()).data
        stray = Message.objects.create(
            chat=other_chat,
            sender=None,
            message_type=MessageType.SYSTEM,
            text_content="x",
        )
        result = self.service.mark_read(
            user=self.b, chat_id=str(self.chat.id), last_read_message_id=str(stray.id)
        )
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_non_participant_forbidden(self) -> None:
        result = self.service.mark_read(
            user=_user(),
            chat_id=str(self.chat.id),
            last_read_message_id=str(self.message.id),
        )
        self.assertEqual(result.error_code, "FORBIDDEN")
