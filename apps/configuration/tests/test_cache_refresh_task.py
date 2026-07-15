"""Tests for the refresh_configuration_cache scheduled task."""

from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase

from apps.configuration.constants import AppConfigKey
from apps.configuration.models import AppConfig
from apps.configuration.services.configuration_service import ConfigurationService
from apps.configuration.tasks.cache_refresh import refresh_configuration_cache


class RefreshConfigurationCacheTaskTests(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_refresh_populates_cache_from_db(self) -> None:
        AppConfig.objects.create(key=AppConfigKey.REVEAL_PRICE_PAISE, value=1234)
        refresh_configuration_cache()
        # Served from cache without touching the DB row again.
        self.assertEqual(ConfigurationService().get_reveal_price_paise(), 1234)
