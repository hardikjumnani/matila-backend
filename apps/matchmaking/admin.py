"""Django admin registration for the matchmaking app (dev-only operator GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import MatchQueue


@admin.register(MatchQueue)
class MatchQueueAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "intent",
        "status",
        "is_online",
        "joined_queue_at",
        "matched_at",
        "last_heartbeat_at",
    )
    list_filter = ("status", "intent", "is_online")
    search_fields = ("id", "user__id", "user__college_email", "matchmaking_session_id")
    raw_id_fields = ("user",)
    readonly_fields = ("joined_queue_at",)
    ordering = ("-joined_queue_at",)
