"""Integration tests for POST /api/v1/auth/session (Firebase SDK mocked)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.colleges.models import College
from apps.users.enums import AccountStatus
from apps.users.models import User

_URL = "/api/v1/auth/session"
_VERIFY = "apps.users.api.views.verify_id_token"


class SessionEndpointTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.uid = "fb_" + uuid.uuid4().hex
        self.email = f"{uuid.uuid4().hex}@college.edu"
        # Supported college for the test sign-up domain (launched in the past).
        College.objects.create(
            code="TEST",
            name="Test College",
            allowed_email_domains=["college.edu"],
            launch_date=timezone.now() - timedelta(days=1),
        )

    def _post(self):
        return self.client.post(_URL, HTTP_AUTHORIZATION="Bearer token")

    def test_first_call_creates_user_and_returns_201(self) -> None:
        with mock.patch(_VERIFY, return_value={"uid": self.uid, "email": self.email}):
            response = self._post()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertTrue(body["data"]["created"])
        self.assertEqual(body["data"]["next_action"], "COMPLETE_ONBOARDING")
        self.assertEqual(User.objects.filter(firebase_uid=self.uid).count(), 1)

    def test_second_call_returns_200_without_recreating(self) -> None:
        with mock.patch(_VERIFY, return_value={"uid": self.uid, "email": self.email}):
            self._post()
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["created"])

    def test_missing_token_returns_401(self) -> None:
        response = self.client.post(_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHORIZED")

    def test_suspended_account_returns_403(self) -> None:
        User.objects.create(
            firebase_uid=self.uid,
            college_email=self.email,
            account_status=AccountStatus.SUSPENDED,
        )
        with mock.patch(_VERIFY, return_value={"uid": self.uid, "email": self.email}):
            response = self._post()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "ACCOUNT_SUSPENDED")
