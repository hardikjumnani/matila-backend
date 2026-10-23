"""Django admin registration for the chats app (operator GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import Chat, ChatParticipant


def _display_name(user) -> str:
    """A participant's best display label: full name, else email, else a hint."""
    if user is None:
        return "-"
    return user.full_name or user.college_email or "(unnamed)"


class ChatParticipantInline(admin.TabularInline):
    model = ChatParticipant
    extra = 0
    raw_id_fields = ("user",)
    readonly_fields = ("user_full_name",)
    fields = (
        "user",
        "user_full_name",
        "status",
        "joined_via",
        "is_chat_hidden",
        "last_read_at",
        "left_at",
    )

    @admin.display(description="Full name")
    def user_full_name(self, obj: ChatParticipant) -> str:
        return _display_name(obj.user)


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user_1",
        "user_2",
        "status",
        "current_phase",
        "matched_intent",
        "message_count",
        "anonymous_chat_extension_count",
        "current_phase_ends_at",
        "last_message_at",
        "created_at",
    )
    list_filter = ("status", "current_phase", "matched_intent", "end_reason")
    search_fields = ("id", "participants__user__full_name", "participants__user__college_email")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    inlines = (ChatParticipantInline,)

    def get_queryset(self, request):
        # Prefetch participants + their users so user_1/user_2 don't N+1 the list.
        return (
            super()
            .get_queryset(request)
            .prefetch_related("participants__user")
        )

    @staticmethod
    def _ordered_participants(obj: Chat) -> list[ChatParticipant]:
        # Oldest-joined first, stable, over the prefetched set.
        return sorted(obj.participants.all(), key=lambda p: p.joined_at)

    @admin.display(description="User 1")
    def user_1(self, obj: Chat) -> str:
        parts = self._ordered_participants(obj)
        return _display_name(parts[0].user) if len(parts) > 0 else "-"

    @admin.display(description="User 2")
    def user_2(self, obj: Chat) -> str:
        parts = self._ordered_participants(obj)
        return _display_name(parts[1].user) if len(parts) > 1 else "-"


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
