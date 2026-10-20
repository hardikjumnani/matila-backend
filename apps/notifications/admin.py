"""Django admin registration for the notifications app (dev-only operator GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import DeviceToken, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "type",
        "title",
        "push_status",
        "priority",
        "is_read",
        "created_at",
    )
    list_filter = ("push_status", "priority", "is_read")
    search_fields = ("id", "user__id", "type", "title")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "platform",
        "device_id",
        "is_active",
        "app_version",
        "last_seen_at",
    )
    list_filter = ("platform", "is_active")
    search_fields = ("id", "user__id", "device_id", "token")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-last_seen_at",)
