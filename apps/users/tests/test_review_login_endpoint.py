"""Integration tests for POST /api/v1/auth/review-login (App Store reviewer bypass).

Firebase custom-token minting is mocked. See AI_BRIDGE [00079].
"""

from __future__ import annotations

from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

_URL = "/api/v1/auth/review-login"
# The service imports create_custom_token lazily from this module at call time.
_MINT = "apps.common.firebase.create_custom_token"


class ReviewLoginEndpointTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        cache.clear()  # reset the scoped throttle between tests

    @override_settings(REVIEW_LOGIN_CODE="")
    def test_disabled_when_code_unset_returns_403(self) -> None:
        resp = self.client.post(_URL, {"code": "anything"}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "FORBIDDEN")

    @override_settings(REVIEW_LOGIN_CODE="s3cret-code")
    def test_bad_code_returns_401(self) -> None:
        resp = self.client.post(_URL, {"code": "wrong"}, format="json")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "UNAUTHORIZED")

    @override_settings(REVIEW_LOGIN_CODE="s3cret-code")
    def test_missing_code_returns_401(self) -> None:
        resp = self.client.post(_URL, {}, format="json")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "UNAUTHORIZED")

    @override_settings(REVIEW_LOGIN_CODE="s3cret-code", REVIEW_DEMO_UID="demo-uid")
    def test_good_code_returns_custom_token(self) -> None:
        with mock.patch(_MINT, return_value="ct_abc123") as minted:
            resp = self.client.post(_URL, {"code": "s3cret-code"}, format="json")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["custom_token"], "ct_abc123")
        minted.assert_called_once_with("demo-uid")

    @override_settings(REVIEW_LOGIN_CODE="s3cret-code")
    def test_mint_failure_returns_500(self) -> None:
        from apps.common.firebase import FirebaseError

        with mock.patch(_MINT, side_effect=FirebaseError("boom")):
            resp = self.client.post(_URL, {"code": "s3cret-code"}, format="json")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()["error"]["code"], "INTERNAL_SERVER_ERROR")

    @override_settings(REVIEW_LOGIN_CODE="s3cret-code")
    def test_unauthenticated_access_allowed(self) -> None:
        # No Authorization header at all: the endpoint must not 401 on auth.
        with mock.patch(_MINT, return_value="ct"):
            resp = self.client.post(_URL, {"code": "s3cret-code"}, format="json")
        self.assertEqual(resp.status_code, 200)
