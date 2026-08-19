"""Common Celery tasks (imported so Celery autodiscovery registers them)."""

from __future__ import annotations

from apps.common.tasks.monitoring import sample_system_metrics

__all__ = ["sample_system_metrics"]
