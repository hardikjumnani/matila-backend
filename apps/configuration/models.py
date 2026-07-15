"""
Configuration domain models.

``FeatureFlag`` and ``AppConfig`` are structurally identical key/value entries
that drive runtime behavior without a deployment. They share an abstract base
to keep the definition DRY; each concrete table enforces its own unique ``key``.
Values are read through ConfigurationService with Redis caching.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import UUIDModel


class RuntimeConfigEntry(UUIDModel):
    """Abstract base for a versionless, admin-editable key/value entry."""

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField(default=dict)
    description = models.TextField(blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{type(self).__name__}<{self.key}>"


class FeatureFlag(RuntimeConfigEntry):
    class Meta(RuntimeConfigEntry.Meta):
        db_table = "feature_flags"


class AppConfig(RuntimeConfigEntry):
    class Meta(RuntimeConfigEntry.Meta):
        db_table = "app_config"
