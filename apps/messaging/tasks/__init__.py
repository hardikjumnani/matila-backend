"""Messaging Celery tasks (imported so Celery autodiscovery registers them)."""

from __future__ import annotations

from apps.messaging.tasks.media_cleanup import cleanup_expired_media

__all__ = ["cleanup_expired_media"]
