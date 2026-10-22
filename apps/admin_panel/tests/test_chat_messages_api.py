"""Admin API tests for the chat transcript endpoint."""

from __future__ import annotations

import uuid

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.chats.models import Chat, ChatParticipant
from apps.messaging.enums import MessageType
from apps.messaging.models import Message
from apps.users.models import User

_ADMIN_EMAIL = "admin@college.edu"


def _user(email=None) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=email or f"{uuid.uuid4().hex}@college.edu",
    )


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminChatMessagesApiTests(TestCase):
    def setUp(self) -> None:
        self.admin = _user(_ADMIN_EMAIL)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.chat = Chat.objects.create()
        self.u1 = _user()
        self.u2 = _user()
        ChatParticipant.objects.create(chat=self.chat, user=self.u1)
        ChatParticipant.objects.create(chat=self.chat, user=self.u2)
        Message.objects.create(
            chat=self.chat, sender=self.u1,
            message_type=MessageType.TEXT, text_content="first",
        )
        Message.objects.create(
            chat=self.chat, sender=self.u2,
            message_type=MessageType.TEXT, text_content="second",
        )

    def test_returns_ordered_transcript(self):
        resp = self.client.get(f"/api/v1/admin/chats/{self.chat.id}/messages")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(
            [m["text_content"] for m in data["messages"]], ["first", "second"]
        )
        self.assertEqual(
            set(data["participant_ids"]), {str(self.u1.id), str(self.u2.id)}
        )
        self.assertEqual(data["chat_id"], str(self.chat.id))

    def test_missing_chat_404(self):
        resp = self.client.get(f"/api/v1/admin/chats/{uuid.uuid4()}/messages")
        self.assertEqual(resp.status_code, 404)

    def test_non_admin_denied(self):
        client = APIClient()
        client.force_authenticate(user=_user())
        self.assertEqual(
            client.get(f"/api/v1/admin/chats/{self.chat.id}/messages").status_code, 403
        )
