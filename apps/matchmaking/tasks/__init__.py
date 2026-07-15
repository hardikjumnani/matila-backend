"""Matchmaking Celery tasks (imported so Celery autodiscovery registers them)."""

from __future__ import annotations

from apps.matchmaking.tasks.queue_cleanup import cleanup_stale_match_queue

__all__ = ["cleanup_stale_match_queue"]
