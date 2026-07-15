"""Model tests for the configuration domain."""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.configuration.models import AppConfig, FeatureFlag


class FeatureFlagModelTests(TestCase):
    def test_key_is_unique(self) -> None:
        FeatureFlag.objects.create(key="payments_enabled", value={"enabled": True})
        with self.assertRaises(IntegrityError), transaction.atomic():
            FeatureFlag.objects.create(key="payments_enabled", value={"enabled": False})

    def test_json_value_roundtrip(self) -> None:
        flag = FeatureFlag.objects.create(key="reveal_enabled", value={"enabled": True})
        flag.refresh_from_db()
        self.assertEqual(flag.value, {"enabled": True})


class AppConfigModelTests(TestCase):
    def test_key_is_unique(self) -> None:
        AppConfig.objects.create(key="reveal_price_paise", value={"amount": 5900})
        with self.assertRaises(IntegrityError), transaction.atomic():
            AppConfig.objects.create(key="reveal_price_paise", value={"amount": 8900})

    def test_feature_flag_and_app_config_keys_are_independent(self) -> None:
        """Same key string is allowed across the two tables (separate uniques)."""
        FeatureFlag.objects.create(key="shared_key", value={})
        AppConfig.objects.create(key="shared_key", value={})
        self.assertEqual(FeatureFlag.objects.count(), 1)
        self.assertEqual(AppConfig.objects.count(), 1)
