"""API tests for the reports endpoints."""

from __future__ import annotations

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from apps.chats.enums import ChatStatus
from apps.chats.services.chat_service import ChatService
from apps.reports.enums import ReportCategory
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


class ReportApiTests(TestCase):
    def setUp(self) -> None:
        self.a = _user()
        self.b = _user()
        self.chat = ChatService().create_chat(self.a, self.b).data

    def _submit(self, user, category=ReportCategory.HARASSMENT):
        return _client(user).post(
            "/api/v1/reports",
            {"chat_id": str(self.chat.id), "category": category},
            format="json",
        )

    def test_submit_freezes_chat(self) -> None:
        response = self._submit(self.a)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["reported_user_id"], str(self.b.id))
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, ChatStatus.ENDED)

    def test_duplicate_conflict(self) -> None:
        self._submit(self.a)
        self.assertEqual(self._submit(self.a).status_code, 409)

    def test_non_participant_forbidden(self) -> None:
        self.assertEqual(self._submit(_user()).status_code, 403)

    def test_list_and_detail_ownership(self) -> None:
        report_id = self._submit(self.a).json()["data"]["id"]
        listing = _client(self.a).get("/api/v1/reports")
        self.assertEqual(len(listing.json()["data"]["items"]), 1)
        own = _client(self.a).get(f"/api/v1/reports/{report_id}")
        self.assertEqual(own.status_code, 200)
        other = _client(self.b).get(f"/api/v1/reports/{report_id}")
        self.assertEqual(other.status_code, 404)
