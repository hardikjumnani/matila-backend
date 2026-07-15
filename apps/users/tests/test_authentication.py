"""Tests for the FirebaseAuthentication DRF class (Firebase SDK mocked)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.test import TestCase
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from apps.common.firebase import InvalidFirebaseToken
from apps.users.authentication import FirebaseAuthentication
from apps.users.enums import AccountStatus
from apps.users.models import User

_PATH = "apps.users.authentication.verify_id_token"


class FirebaseAuthenticationTests(TestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()
        self.auth = FirebaseAuthentication()
        self.uid = "fb_" + uuid.uuid4().hex

    def _request(self, token: str | None):
        headers = {}
        if token is not None:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return self.factory.get("/api/v1/ping", **headers)

    def _user(self, **overrides) -> User:
        data = {"firebase_uid": self.uid, "college_email": "a@college.edu"}
        data.update(overrides)
        return User.objects.create(**data)

    def test_no_header_returns_none(self) -> None:
        self.assertIsNone(self.auth.authenticate(self._request(None)))

    def test_malformed_header_raises(self) -> None:
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer a b")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_invalid_token_raises(self) -> None:
        with mock.patch(_PATH, side_effect=InvalidFirebaseToken()):
            with self.assertRaises(AuthenticationFailed):
                self.auth.authenticate(self._request("bad"))

    def test_valid_token_without_user_raises(self) -> None:
        with mock.patch(_PATH, return_value={"uid": self.uid}):
            with self.assertRaises(AuthenticationFailed):
                self.auth.authenticate(self._request("good"))

    def test_valid_token_active_user_authenticates(self) -> None:
        user = self._user()
        with mock.patch(
            _PATH, return_value={"uid": self.uid, "email": "a@college.edu"}
        ):
            result = self.auth.authenticate(self._request("good"))
        self.assertIsNotNone(result)
        self.assertEqual(result[0].id, user.id)

    def test_suspended_user_is_denied(self) -> None:
        self._user(account_status=AccountStatus.SUSPENDED)
        with mock.patch(_PATH, return_value={"uid": self.uid}):
            with self.assertRaises(AuthenticationFailed) as ctx:
                self.auth.authenticate(self._request("good"))
        self.assertEqual(ctx.exception.detail["code"], "ACCOUNT_SUSPENDED")

    def test_banned_user_is_denied(self) -> None:
        self._user(account_status=AccountStatus.BANNED)
        with mock.patch(_PATH, return_value={"uid": self.uid}):
            with self.assertRaises(AuthenticationFailed) as ctx:
                self.auth.authenticate(self._request("good"))
        self.assertEqual(ctx.exception.detail["code"], "ACCOUNT_BANNED")
