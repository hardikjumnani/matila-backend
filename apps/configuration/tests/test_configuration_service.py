"""Tests for ConfigurationService (caching, defaults, typed accessors)."""

from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase

from apps.configuration.constants import AppConfigKey, FeatureFlagKey
from apps.configuration.models import AppConfig, FeatureFlag
from apps.configuration.services.configuration_service import ConfigurationService


class ConfigurationServiceTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.service = ConfigurationService()

    def test_returns_default_when_unset(self) -> None:
        self.assertEqual(self.service.get_reveal_price_paise(), 3900)
        self.assertEqual(self.service.get_chat_extension_price_paise(), 2900)

    def test_database_value_overrides_default(self) -> None:
        AppConfig.objects.create(key=AppConfigKey.REVEAL_PRICE_PAISE, value=7500)
        self.assertEqual(self.service.get_reveal_price_paise(), 7500)

    def test_value_is_cached_after_first_read(self) -> None:
        AppConfig.objects.create(key=AppConfigKey.REVEAL_PRICE_PAISE, value=7500)
        self.assertEqual(self.service.get_reveal_price_paise(), 7500)
        # Mutating the row directly bypasses invalidation; cache still serves old.
        AppConfig.objects.filter(key=AppConfigKey.REVEAL_PRICE_PAISE).update(value=100)
        self.assertEqual(self.service.get_reveal_price_paise(), 7500)
        # Explicit invalidation makes the new value visible.
        self.service.invalidate_config(AppConfigKey.REVEAL_PRICE_PAISE)
        self.assertEqual(self.service.get_reveal_price_paise(), 100)

    def test_feature_flag_default_and_override(self) -> None:
        self.assertTrue(self.service.is_feature_enabled(FeatureFlagKey.REVEAL_ENABLED))
        FeatureFlag.objects.create(key=FeatureFlagKey.REVEAL_ENABLED, value=False)
        self.service.invalidate_flag(FeatureFlagKey.REVEAL_ENABLED)
        self.assertFalse(self.service.is_feature_enabled(FeatureFlagKey.REVEAL_ENABLED))

    def test_maintenance_mode_default_false(self) -> None:
        self.assertFalse(self.service.is_maintenance_mode())

    def test_get_all_config_merges_defaults_and_overrides(self) -> None:
        AppConfig.objects.create(key=AppConfigKey.SUPPORT_EMAIL, value="help@x.edu")
        merged = self.service.get_all_config()
        self.assertEqual(merged[AppConfigKey.SUPPORT_EMAIL], "help@x.edu")
        self.assertEqual(merged[AppConfigKey.REVEAL_PRICE_PAISE], 3900)

    def test_refresh_cache_populates_from_db(self) -> None:
        AppConfig.objects.create(key=AppConfigKey.MATCHMAKING_TIMEOUT_SECONDS, value=42)
        self.service.refresh_cache()
        self.assertEqual(self.service.get_matchmaking_timeout_seconds(), 42)
