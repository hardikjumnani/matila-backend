"""Application configuration for the Matchmaking domain."""

from __future__ import annotations

from django.apps import AppConfig


class MatchmakingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.matchmaking"
    verbose_name = "Matchmaking"
