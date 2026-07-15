"""API tests for the chats endpoints."""

from __future__ import annotations

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from apps.chats.enums import ChatPhase, ChatStatus
from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.messaging.enums import MessageType
from apps.messaging.models import Message
from apps.users.models import User


def _user(name="") -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        full_name=name,
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class ChatApiTests(TestCase):
    def setUp(self) -> None:
        self.a = _user("Alice")
        self.b = _user("Bob")
        self.chat = ChatService().create_chat(self.a, self.b).data
        self.client = _client(self.a)

    def test_list_returns_chat(self) -> None:
        response = self.client.get("/api/v1/chats")
        self.assertEqual(response.status_code, 200)
        items = response.json()["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], str(self.chat.id))

    def test_detail_masks_identity_while_anonymous(self) -> None:
        response = self.client.get(f"/api/v1/chats/{self.chat.id}")
        data = response.json()["data"]
        self.assertFalse(data["identity_visible"])
        self.assertIsNone(data["other_participant"]["display_name"])
        self.assertEqual(data["other_participant"]["user_id"], str(self.b.id))

    def test_detail_reveals_identity_when_revealed(self) -> None:
        Chat.objects.filter(id=self.chat.id).update(
            status=ChatStatus.REVEALED, current_phase=ChatPhase.REVEALED
        )
        response = self.client.get(f"/api/v1/chats/{self.chat.id}")
        data = response.json()["data"]
        self.assertTrue(data["identity_visible"])
        self.assertEqual(data["other_participant"]["display_name"], "Bob")

    def test_non_participant_forbidden(self) -> None:
        response = _client(_user()).get(f"/api/v1/chats/{self.chat.id}")
        self.assertEqual(response.status_code, 403)

    def test_unknown_chat_not_found(self) -> None:
        response = self.client.get(f"/api/v1/chats/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)

    def test_leave_ends_chat(self) -> None:
        response = self.client.post(f"/api/v1/chats/{self.chat.id}/leave")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], ChatStatus.ENDED)

    def test_hide_removes_from_list(self) -> None:
        self.client.post(f"/api/v1/chats/{self.chat.id}/hide")
        response = self.client.get("/api/v1/chats")
        self.assertEqual(len(response.json()["data"]["items"]), 0)

    def test_expiry_reports_remaining_seconds(self) -> None:
        response = self.client.get(f"/api/v1/chats/{self.chat.id}/expiry")
        data = response.json()["data"]
        self.assertIsNotNone(data["seconds_remaining"])
        self.assertGreater(data["seconds_remaining"], 0)

    def test_read_advances_pointer(self) -> None:
        message = Message.objects.create(
            chat=self.chat,
            sender=self.a,
            message_type=MessageType.TEXT,
            text_content="hi",
        )
        response = self.client.post(
            f"/api/v1/chats/{self.chat.id}/read",
            {"last_read_message_id": str(message.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["ok"])
