"""Django admin registration for the colleges app (dev-only operator GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import College, LaunchNotification


@admin.register(College)
class CollegeAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "name", "is_active", "launch_date", "created_at")
    list_filter = ("is_active",)
    search_fields = ("id", "code", "name")
    readonly_fields = ("created_at",)
    ordering = ("name",)


@admin.register(LaunchNotification)
class LaunchNotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "college", "milestone", "sent_at")
    list_filter = ("milestone",)
    search_fields = ("id", "college__code")
    raw_id_fields = ("college",)
    readonly_fields = ("sent_at",)
