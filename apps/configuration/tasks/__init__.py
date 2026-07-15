"""Configuration Celery tasks (imported so Celery autodiscovery registers them)."""

from __future__ import annotations

from apps.configuration.tasks.cache_refresh import refresh_configuration_cache

__all__ = ["refresh_configuration_cache"]
