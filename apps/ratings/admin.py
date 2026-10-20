"""Django admin registration for the ratings app (dev-only operator GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import Rating


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "chat",
        "rated_by",
        "rated_user",
        "questionnaire_version",
        "created_at",
    )
    list_filter = ("questionnaire_version",)
    search_fields = ("id", "chat__id", "rated_by__id", "rated_user__id")
    raw_id_fields = ("chat", "rated_by", "rated_user")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
