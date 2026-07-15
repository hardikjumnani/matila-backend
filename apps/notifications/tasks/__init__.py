"""Notification Celery tasks (imported so Celery autodiscovery registers them)."""

from __future__ import annotations

from apps.notifications.tasks.push import send_push_notification

__all__ = ["send_push_notification"]
