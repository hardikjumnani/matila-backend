"""Django admin registration for the reports app (dev-only operator GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "chat",
        "reported_by",
        "reported_user",
        "category",
        "status",
        "resolution_action",
        "is_false_report",
        "created_at",
    )
    list_filter = ("status", "category", "resolution_action", "is_false_report")
    search_fields = ("id", "chat__id", "reported_by__id", "reported_user__id")
    raw_id_fields = ("chat", "reported_by", "reported_user", "reported_message")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
