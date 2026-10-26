"""Admin API tests for the suspicion (second-hand Veil) surface."""

from __future__ import annotations

import uuid

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.chats.models import Chat
from apps.privacy.enums import SuspicionReviewStatus
from apps.privacy.models import SuspicionEvent, UserSuspicionProfile
from apps.users.models import User

_ADMIN_EMAIL = "admin@college.edu"


def _user(email=None) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=email or f"{uuid.uuid4().hex}@college.edu",
    )


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminSuspicionApiTests(TestCase):
    def setUp(self) -> None:
        self.admin = _user(_ADMIN_EMAIL)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.target = _user()
        self.chat = Chat.objects.create()
        self.event = SuspicionEvent.objects.create(
            chat=self.chat,
            user=self.target,
            signals=[{"signal": "NEAR_MISS", "weight": 3, "span": "insta"}],
            top_signal="NEAR_MISS",
            score=3,
            rule_version="test",
            raw_message="ping me on insta",
        )
        self.profile = UserSuspicionProfile.objects.create(
            user=self.target, score=3, priority_score=3, tier="WATCH", event_count=1
        )

    def test_suspicion_events_feed(self):
        resp = self.client.get("/api/v1/admin/safety/suspicion-events")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["data"]["items"]
        self.assertTrue(any(i["id"] == str(self.event.id) for i in items))

    def test_suspicion_events_filter_by_user(self):
        resp = self.client.get(
            f"/api/v1/admin/safety/suspicion-events?user_id={self.target.id}"
        )
        items = resp.json()["data"]["items"]
        self.assertEqual({i["user_id"] for i in items}, {str(self.target.id)})

    def test_suspicion_offenders(self):
        resp = self.client.get("/api/v1/admin/safety/suspicion-offenders")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()["data"]
        row = next(r for r in rows if r["user_id"] == str(self.target.id))
        self.assertEqual(row["tier"], "WATCH")
        self.assertEqual(row["priority_score"], 3)

    def test_reset_clears_score_and_audits(self):
        resp = self.client.post(
            f"/api/v1/admin/safety/users/{self.target.id}/suspicion/reset",
            {"notes": "false accumulation"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.score, 0)
        self.assertEqual(self.profile.priority_score, 0)
        self.assertEqual(self.profile.tier, "CLEAN")
        self.assertEqual(self.profile.review_status, SuspicionReviewStatus.CLEARED.value)
        self.assertTrue(
            AuditLog.objects.filter(
                action="safety.suspicion_score_reset", entity_id=str(self.target.id)
            ).exists()
        )

    def test_review_sets_status_and_audits(self):
        resp = self.client.post(
            f"/api/v1/admin/safety/users/{self.target.id}/suspicion/review",
            {"status": "CLEARED", "notes": "benign poetry"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.review_status, SuspicionReviewStatus.CLEARED.value)
        self.assertEqual(self.profile.notes, "benign poetry")
        self.assertTrue(
            AuditLog.objects.filter(
                action="safety.suspicion_reviewed", entity_id=str(self.target.id)
            ).exists()
        )

    def test_user_safety_includes_suspicion(self):
        resp = self.client.get(f"/api/v1/admin/safety/users/{self.target.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["suspicion"]["score"], 3)
        self.assertEqual(len(data["recent_suspicion_events"]), 1)

    def test_non_admin_denied(self):
        client = APIClient()
        client.force_authenticate(user=_user())
        self.assertEqual(
            client.get("/api/v1/admin/safety/suspicion-events").status_code, 403
        )
