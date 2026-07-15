"""API test for the public /config endpoint."""

from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient


class ConfigEndpointTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.client = APIClient()

    def test_config_is_public_and_wrapped(self) -> None:
        response = self.client.get("/api/v1/config")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        data = body["data"]
        self.assertIn("feature_flags", data)
        self.assertEqual(data["pricing"]["reveal_price_paise"], 5900)
        self.assertIn("app_version", data)
