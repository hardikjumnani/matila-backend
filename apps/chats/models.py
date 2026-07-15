"""
Chats domain models.

``Chat`` holds the lifecycle state machine; ``ChatParticipant`` maps the two
users into a chat and tracks per-user read/hide state. Chats are retained
indefinitely and become read-only once ended — state is expressed through the
``status`` field, never by deleting rows.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel

from .enums import (
    ChatPhase,
    ChatStatus,
    EndReason,
    JoinedVia,
    ParticipantStatus,
)


class Chat(UUIDModel):
    status = models.CharField(
        max_length=10,
        choices=ChatStatus.choices,
        default=ChatStatus.ACTIVE,
    )
    current_phase = models.CharField(
        max_length=10,
        choices=ChatPhase.choices,
        default=ChatPhase.ANONYMOUS,
    )
    end_reason = models.CharField(
        max_length=10, choices=EndReason.choices, blank=True, default=""
    )

    # Timestamp of the most recent status transition; updated by ChatService on
    # every transition (not auto_now, which would fire on any save).
    status_changed_at = models.DateTimeField(default=timezone.now)
    # When the current phase ends (e.g. the 72h anonymous window). Drives the
    # chat-expiry background task.
    current_phase_ends_at = models.DateTimeField(null=True, blank=True)

    message_count = models.PositiveIntegerField(default=0)
    anonymous_chat_extension_count = models.PositiveIntegerField(default=0)

    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "chats"
        ordering = ["-created_at"]
        indexes = [
            # Expiry task: find ACTIVE/EXTENDED chats whose phase window elapsed.
            models.Index(
                fields=["status", "current_phase_ends_at"],
                name="idx_chat_status_phase_end",
            ),
        ]

    def __str__(self) -> str:
        return f"Chat<{self.id}> {self.status}/{self.current_phase}"


class ChatParticipant(UUIDModel):
    chat = models.ForeignKey(
        Chat,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="chat_participations",
    )

    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.ACTIVE,
    )

    # Read-receipt pointer. Stored as an opaque message id (UUID) rather than a
    # ForeignKey to messaging.Message: a hard FK would create a circular
    # dependency between the chats and messaging apps (Message already points at
    # Chat). The WebSocket protocol also treats last_read_message_id as an
    # opaque id.
    last_read_message_id = models.UUIDField(null=True, blank=True)
    last_read_at = models.DateTimeField(null=True, blank=True)

    is_chat_hidden = models.BooleanField(default=False)
    hidden_at = models.DateTimeField(null=True, blank=True)

    joined_via = models.CharField(
        max_length=10,
        choices=JoinedVia.choices,
        default=JoinedVia.MATCH,
    )

    class Meta:
        db_table = "chat_participants"
        constraints = [
            models.UniqueConstraint(
                fields=["chat", "user"],
                name="uniq_participant_per_chat_user",
            ),
        ]
        indexes = [
            # "List this user's chats" and "one active chat per user" lookups.
            models.Index(fields=["user", "status"], name="idx_participant_user_status"),
        ]

    def __str__(self) -> str:
        return f"ChatParticipant<{self.id}> chat={self.chat_id} user={self.user_id}"
