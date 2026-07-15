"""API tests for the ratings endpoints."""

from __future__ import annotations

import uuid

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.chats.enums import EndReason
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


class RatingApiTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.a = _user()
        self.b = _user()
        self.chats = ChatService()
        self.chat = self.chats.create_chat(self.a, self.b).data

    def _end(self) -> None:
        self.chats.end_chat(str(self.chat.id), reason=EndReason.USER_EXIT)

    def test_questionnaire(self) -> None:
        response = _client(self.a).get(
            f"/api/v1/chats/{self.chat.id}/rating-questionnaire"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["version"], "v1")

    def test_submit_after_end(self) -> None:
        self._end()
        response = _client(self.a).post(
            f"/api/v1/chats/{self.chat.id}/ratings",
            {"questionnaire_version": "v1", "responses": {"would_chat_again": "YES"}},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["rated_user_id"], str(self.b.id))

    def test_cannot_rate_active_chat(self) -> None:
        response = _client(self.a).post(
            f"/api/v1/chats/{self.chat.id}/ratings",
            {"questionnaire_version": "v1", "responses": {"would_chat_again": "YES"}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_status(self) -> None:
        self._end()
        before = _client(self.a).get(f"/api/v1/chats/{self.chat.id}/rating-status")
        self.assertFalse(before.json()["data"]["has_rated"])
        _client(self.a).post(
            f"/api/v1/chats/{self.chat.id}/ratings",
            {"questionnaire_version": "v1", "responses": {"would_chat_again": "YES"}},
            format="json",
        )
        after = _client(self.a).get(f"/api/v1/chats/{self.chat.id}/rating-status")
        self.assertTrue(after.json()["data"]["has_rated"])

    def test_non_participant_forbidden(self) -> None:
        self._end()
        response = _client(_user()).get(
            f"/api/v1/chats/{self.chat.id}/rating-questionnaire"
        )
        self.assertEqual(response.status_code, 403)
