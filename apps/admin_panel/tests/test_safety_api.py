"""API tests for the admin Trust & Safety endpoints (Veil / Muffle review)."""

from __future__ import annotations

import uuid

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.privacy.enums import (
    LeakAction,
    LeakCategory,
    LeakSeverity,
    MuffleMode,
    ProfanityTier,
    VeilMode,
)
from apps.privacy.models import LeakEvent, LeakStrike, ProfanityEvent
from apps.users.models import User

_ADMIN_EMAIL = "admin@college.edu"


def _user(email=None) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=email or f"{uuid.uuid4().hex}@college.edu",
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminSafetyAccessTests(TestCase):
    def test_non_admin_forbidden(self) -> None:
        response = _client(_user()).get("/api/v1/admin/safety/leak-events")
        self.assertEqual(response.status_code, 403)

    def test_admin_allowed(self) -> None:
        response = _client(_user(_ADMIN_EMAIL)).get("/api/v1/admin/safety/leak-events")
        self.assertEqual(response.status_code, 200)


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminSafetyTests(TestCase):
    def setUp(self) -> None:
        self.admin = _user(_ADMIN_EMAIL)
        self.client = _client(self.admin)
        self.target = _user()
        LeakEvent.objects.create(
            user=self.target,
            category=LeakCategory.PHONE.value,
            severity=LeakSeverity.HIGH.value,
            action=LeakAction.BLOCK.value,
            mode=VeilMode.ENFORCE.value,
            rule_version="v1",
            detectors=["phone"],
            raw_message="call me 9876543210",
            matched_span="9876543210",
        )
        ProfanityEvent.objects.create(
            user=self.target,
            tier=ProfanityTier.T1_HARSH.value,
            mode=MuffleMode.MASK.value,
            rule_version="v1",
            words=["motherfucker"],
            raw_message="you motherfucker",
            masked_message="you mo*he*fu*ker",
        )
        LeakStrike.objects.create(
            user=self.target, count=3, last_event_at=timezone.now()
        )

    def test_leak_events_list(self) -> None:
        body = self.client.get("/api/v1/admin/safety/leak-events").json()["data"]
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["category"], LeakCategory.PHONE.value)
        self.assertIn("9876543210", body["items"][0]["raw_message"])

    def test_leak_events_filter_by_user(self) -> None:
        other = _user()
        LeakEvent.objects.create(
            user=other,
            category=LeakCategory.EMAIL.value,
            severity=LeakSeverity.HIGH.value,
            action=LeakAction.BLOCK.value,
            mode=VeilMode.ENFORCE.value,
            rule_version="v1",
        )
        url = f"/api/v1/admin/safety/leak-events?user_id={self.target.id}"
        items = self.client.get(url).json()["data"]["items"]
        self.assertEqual(len(items), 1)

    def test_profanity_events_list(self) -> None:
        items = self.client.get(
            "/api/v1/admin/safety/profanity-events"
        ).json()["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["tier"], ProfanityTier.T1_HARSH.value)

    def test_offenders(self) -> None:
        offenders = self.client.get("/api/v1/admin/safety/offenders").json()["data"]
        self.assertEqual(len(offenders), 1)
        row = offenders[0]
        self.assertEqual(row["user_id"], str(self.target.id))
        self.assertEqual(row["strike_count"], 3)
        self.assertEqual(row["leak_count"], 1)
        self.assertEqual(row["profanity_count"], 1)

    def test_user_safety_detail(self) -> None:
        body = self.client.get(
            f"/api/v1/admin/safety/users/{self.target.id}"
        ).json()["data"]
        self.assertEqual(body["strikes"]["count"], 3)
        self.assertEqual(len(body["recent_leak_events"]), 1)
        self.assertEqual(len(body["recent_profanity_events"]), 1)
        self.assertEqual(body["counts"]["leak_by_category"][LeakCategory.PHONE.value], 1)

    def test_user_safety_detail_404(self) -> None:
        response = self.client.get(f"/api/v1/admin/safety/users/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)

    def test_stats(self) -> None:
        body = self.client.get("/api/v1/admin/safety/stats").json()["data"]
        self.assertEqual(body["leak_events"]["last_7d"], 1)
        self.assertEqual(body["profanity_events"]["last_7d"], 1)
        self.assertEqual(body["open_offenders"], 1)

    def test_reset_strikes(self) -> None:
        response = self.client.post(
            f"/api/v1/admin/safety/users/{self.target.id}/reset-strikes",
            {"notes": "false positive"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["strike_count"], 0)
        self.target.refresh_from_db()
        self.assertEqual(LeakStrike.objects.get(user=self.target).count, 0)
