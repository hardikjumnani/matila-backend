"""Reveal Celery tasks (imported so Celery autodiscovery registers them)."""

from __future__ import annotations

from apps.reveal.tasks.auto_exit import auto_exit_stale_decisions

__all__ = ["auto_exit_stale_decisions"]
