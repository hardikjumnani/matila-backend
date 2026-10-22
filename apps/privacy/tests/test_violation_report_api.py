"""API tests for the frontend violation-report endpoint."""

from __future__ import annotations

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from apps.chats.models import Chat
from apps.privacy.enums import ViolationSource
from apps.privacy.models import LeakEvent, LeakStrike
from apps.users.models import User

_URL = "/api/v1/privacy/violations"


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        full_name="Reporter",
    )


class ViolationReportApiTests(TestCase):
    def setUp(self) -> None:
        self.user = _user()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_records_frontend_violation_and_bumps_strike(self):
        resp = self.client.post(
            _URL,
            {
                "attempted_text": "my number is 9876543210",
                "category": "PHONE",
                "client_detectors": ["fe_phone"],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.json()["data"]["recorded"])
        event = LeakEvent.objects.get(user=self.user)
        self.assertEqual(event.source, ViolationSource.FRONTEND.value)
        self.assertEqual(event.category, "PHONE")
        self.assertEqual(event.raw_message, "my number is 9876543210")
        # Counts as a violation (owner decision): the strike counter is bumped.
        self.assertEqual(LeakStrike.objects.get(user=self.user).count, 1)

    def test_unknown_category_coerced(self):
        resp = self.client.post(
            _URL,
            {"attempted_text": "something", "category": "NOT_A_CATEGORY"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(LeakEvent.objects.get(user=self.user).category, "PLATFORM")

    def test_chat_must_belong_to_caller(self):
        other_chat = Chat.objects.create()  # caller is not a participant
        resp = self.client.post(
            _URL,
            {"attempted_text": "hi", "chat_id": str(other_chat.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "FORBIDDEN")
        self.assertFalse(LeakEvent.objects.filter(user=self.user).exists())

    def test_requires_auth(self):
        anon = APIClient()
        resp = anon.post(_URL, {"attempted_text": "hi"}, format="json")
        self.assertEqual(resp.status_code, 401)

    def test_empty_text_rejected(self):
        resp = self.client.post(_URL, {"attempted_text": ""}, format="json")
        self.assertEqual(resp.status_code, 400)
