"""API tests for the reveal endpoints."""

from __future__ import annotations

import uuid

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class RevealApiTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.a = _user()
        self.b = _user()
        self.chat = ChatService().create_chat(self.a, self.b).data
        Chat.objects.filter(id=self.chat.id).update(message_count=100)  # eligible

    def test_eligibility(self) -> None:
        response = _client(self.a).get(
            f"/api/v1/chats/{self.chat.id}/reveal-eligibility"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["eligible"])

    def test_mutual_intent_flow(self) -> None:
        first = _client(self.a).post(f"/api/v1/chats/{self.chat.id}/reveal-intent")
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["data"]["mutual"])

        second = _client(self.b).post(f"/api/v1/chats/{self.chat.id}/reveal-intent")
        data = second.json()["data"]
        self.assertTrue(data["mutual"])
        self.assertTrue(data["payment_required"])

    def test_status(self) -> None:
        _client(self.a).post(f"/api/v1/chats/{self.chat.id}/reveal-intent")
        response = _client(self.a).get(f"/api/v1/chats/{self.chat.id}/reveal-status")
        self.assertEqual(response.json()["data"]["my_intent_status"], "PENDING")

    def test_non_participant_forbidden(self) -> None:
        response = _client(_user()).get(
            f"/api/v1/chats/{self.chat.id}/reveal-eligibility"
        )
        self.assertEqual(response.status_code, 403)
