"""Django admin registration for the configuration app (dev-only operator GUI).

NOTE: In the running app, config/flags are read through ConfigurationService with
Redis caching. Editing a value here changes the DB row; the service cache is
refreshed on write through its own API, so a bare admin edit may take effect only
after the cache entry expires or is cleared.
"""

from __future__ import annotations

from django.contrib import admin

from .models import AppConfig, FeatureFlag


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "value", "updated_at", "updated_by")
    search_fields = ("id", "key", "description")
    raw_id_fields = ("updated_by",)
    readonly_fields = ("updated_at",)
    ordering = ("key",)


@admin.register(AppConfig)
class AppConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "value", "updated_at", "updated_by")
    search_fields = ("id", "key", "description")
    raw_id_fields = ("updated_by",)
    readonly_fields = ("updated_at",)
    ordering = ("key",)
