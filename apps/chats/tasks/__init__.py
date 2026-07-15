"""Chat Celery tasks (imported so Celery autodiscovery registers them)."""

from __future__ import annotations

from apps.chats.tasks.expiry import expire_chats

__all__ = ["expire_chats"]
