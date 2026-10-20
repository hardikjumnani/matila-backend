"""Django admin registration for the chats app (dev-only operator GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import Chat, ChatParticipant


class ChatParticipantInline(admin.TabularInline):
    model = ChatParticipant
    extra = 0
    raw_id_fields = ("user",)
    fields = (
        "user",
        "status",
        "joined_via",
        "is_chat_hidden",
        "last_read_at",
        "left_at",
    )


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "current_phase",
        "message_count",
        "anonymous_chat_extension_count",
        "current_phase_ends_at",
        "last_message_at",
        "created_at",
    )
    list_filter = ("status", "current_phase", "end_reason")
    search_fields = ("id",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    inlines = (ChatParticipantInline,)


@admin.register(ChatParticipant)
class ChatParticipantAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "chat",
        "user",
        "status",
        "joined_via",
        "is_chat_hidden",
        "joined_at",
    )
    list_filter = ("status", "joined_via", "is_chat_hidden")
    search_fields = ("id", "chat__id", "user__id", "user__college_email")
    raw_id_fields = ("chat", "user")
    readonly_fields = ("joined_at",)
