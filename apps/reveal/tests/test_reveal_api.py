"""API tests for the decision / safe-reveal / eligibility endpoints."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.users.enums import Gender
from apps.users.models import User


def _user(gender: str) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        gender=gender,
        intent="RELATIONSHIP",
        gender_preferences=[Gender.MALE, Gender.FEMALE],
    )


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class DecisionApiTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.boy = _user(Gender.MALE)
        self.girl = _user(Gender.FEMALE)
        self.chat = ChatService().create_chat(self.boy, self.girl).data
        Chat.objects.filter(id=self.chat.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )

    def test_eligibility_endpoint(self) -> None:
        resp = _client(self.boy).get(
            f"/api/v1/chats/{self.chat.id}/reveal-eligibility"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["data"]["eligible"])

    def test_get_decision_state(self) -> None:
        resp = _client(self.girl).get(f"/api/v1/chats/{self.chat.id}/decision")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("SAFE_REVEAL", data["available_choices"])
        self.assertIn("REVEAL", data["available_choices"])

    def test_submit_decision_records_and_waits(self) -> None:
        resp = _client(self.boy).post(
            f"/api/v1/chats/{self.chat.id}/decision", {"choice": "REVEAL"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["my_choice"], "REVEAL")
        self.assertFalse(data["other_chosen"])

    def test_submit_decision_invalid_choice_400(self) -> None:
        resp = _client(self.boy).post(
            f"/api/v1/chats/{self.chat.id}/decision", {"choice": "SAFE_REVEAL"}
        )
        # Boy cannot pick SAFE_REVEAL → not available → VALIDATION_ERROR (400).
        self.assertEqual(resp.status_code, 400)

    def test_exit_ends_chat_via_api(self) -> None:
        resp = _client(self.boy).post(
            f"/api/v1/chats/{self.chat.id}/decision", {"choice": "EXIT"}
        )
        self.assertEqual(resp.status_code, 200)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, "ENDED")

    def test_safe_decision_requires_active_phase(self) -> None:
        resp = _client(self.girl).post(
            f"/api/v1/chats/{self.chat.id}/safe-reveal/decision",
            {"choice": "REVEAL_YOURSELF"},
        )
        self.assertEqual(resp.status_code, 409)
