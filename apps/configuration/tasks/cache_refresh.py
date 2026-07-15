"""Scheduled task: refresh the runtime configuration cache."""

from __future__ import annotations

import logging

from celery import shared_task

from apps.configuration.services.configuration_service import ConfigurationService

logger = logging.getLogger(__name__)


@shared_task(name="apps.configuration.tasks.refresh_configuration_cache")
def refresh_configuration_cache() -> None:
    """Repopulate the Redis cache for app_config and feature_flags."""
    ConfigurationService().refresh_cache()
