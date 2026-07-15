"""Application configuration for the Chats domain."""

from __future__ import annotations

from django.apps import AppConfig


class ChatsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.chats"
    verbose_name = "Chats"
