"""College Celery tasks (imported so Celery autodiscovery registers them)."""

from __future__ import annotations

from apps.colleges.tasks.launch import send_launch_notifications

__all__ = ["send_launch_notifications"]
