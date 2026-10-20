"""Django admin registration for the privacy app (Veil / Muffle; dev-only GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import LeakEvent, LeakStrike, ProfanityEvent


@admin.register(LeakEvent)
class LeakEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "chat",
        "category",
        "severity",
        "action",
        "mode",
        "created_at",
    )
    list_filter = ("category", "severity", "action", "mode")
    search_fields = ("id", "user__id", "chat__id", "raw_message", "matched_span")
    raw_id_fields = ("user", "chat")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(ProfanityEvent)
class ProfanityEventAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "chat", "tier", "mode", "created_at")
    list_filter = ("tier", "mode")
    search_fields = ("id", "user__id", "chat__id", "raw_message", "masked_message")
    raw_id_fields = ("user", "chat")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(LeakStrike)
class LeakStrikeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "count", "last_event_at", "updated_at")
    search_fields = ("id", "user__id", "user__college_email")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
