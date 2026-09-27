"""API tests for the matchmaking endpoints."""

from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User


def _eligible(gender: str, intent: str, prefs: list[str]) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        gender=gender,
        intent=intent,
        gender_preferences=prefs,
        verification_status=VerificationStatus.APPROVED,
        onboarding_completed_at=timezone.now(),
    )


def _client_for(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class MatchmakingApiTests(TestCase):
    def test_unverified_user_forbidden(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        user.verification_status = VerificationStatus.PENDING
        user.save(update_fields=["verification_status"])
        response = _client_for(user).post("/api/v1/matchmaking/join")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "VERIFICATION_REQUIRED")

    def test_join_without_partner(self) -> None:
        user = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        response = _client_for(user).post("/api/v1/matchmaking/join")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertFalse(data["matched"])
        self.assertIsNotNone(data["queue_entry_id"])

    def test_two_compatible_users_match(self) -> None:
        a = _eligible(Gender.MALE, Intent.RELATIONSHIP, [Gender.FEMALE])
        b = _eligible(Gender.FEMALE, Intent.RELATIONSHIP, [Gender.MALE])
        _client_for(a).post("/api/v1/matchmaking/join")
        response = _client_for(b).post("/api/v1/matchmaking/join")
        data = response.json()["data"]
        self.assertTrue(data["matched"])
        self.assertIsNotNone(data["chat_id"])

    def test_status_and_leave(self) -> None:
        user = _eligible(Gender.MALE, Intent.CASUAL, [Gender.FEMALE])
        client = _client_for(user)
        client.post("/api/v1/matchmaking/join")
        status = client.get("/api/v1/matchmaking/status")
        self.assertEqual(status.json()["data"]["state"], "SEARCHING")
        client.post("/api/v1/matchmaking/leave")
        status = client.get("/api/v1/matchmaking/status")
        self.assertEqual(status.json()["data"]["state"], "IDLE")

    def test_heartbeat_without_entry(self) -> None:
        user = _eligible(Gender.MALE, Intent.CASUAL, [Gender.FEMALE])
        response = _client_for(user).post("/api/v1/matchmaking/heartbeat")
        self.assertEqual(response.status_code, 404)

    def test_active_range(self) -> None:
        user = _eligible(Gender.MALE, Intent.CASUAL, [Gender.FEMALE])
        response = _client_for(user).get("/api/v1/matchmaking/active-range")
        self.assertEqual(response.status_code, 200)
        self.assertIn("label", response.json()["data"])
