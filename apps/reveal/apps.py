"""Application configuration for the Reveal domain."""

from __future__ import annotations

from django.apps import AppConfig


class RevealConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reveal"
    verbose_name = "Reveal"
