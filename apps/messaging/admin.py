"""Django admin registration for the messaging app (dev-only operator GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "chat",
        "sender",
        "message_type",
        "text_content",
        "is_deleted",
        "created_at",
    )
    list_filter = ("message_type", "is_deleted", "media_visibility", "media_status")
    search_fields = ("id", "chat__id", "sender__id", "text_content")
    raw_id_fields = ("chat", "sender", "reply_to_message")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
