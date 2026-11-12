"""Chat Celery tasks (imported so Celery autodiscovery registers them)."""

from __future__ import annotations

from apps.chats.tasks.expiry import expire_chats
from apps.chats.tasks.reminders import send_expiry_reminders

__all__ = ["expire_chats", "send_expiry_reminders"]
