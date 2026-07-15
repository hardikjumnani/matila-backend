"""
Messaging domain models.

Messages are immutable (no editing) and support soft deletion only. Media
messages carry view-once semantics and a media lifecycle (available → viewed /
expired → deleted); the media itself lives in S3 and is purged by a background
job after 7 days, while the message row is retained for chat history.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import UUIDModel

from .enums import MediaStatus, MediaVisibility, MessageType


class Message(UUIDModel):
    chat = models.ForeignKey(
        "chats.Chat",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    # Null for SYSTEM messages, which have no human sender.
    sender = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="messages",
        null=True,
        blank=True,
    )
    message_type = models.CharField(
        max_length=10,
        choices=MessageType.choices,
        default=MessageType.TEXT,
    )

    text_content = models.TextField(blank=True, default="")
    media_url = models.URLField(max_length=512, blank=True, default="")

    # Self-referential reply pointer within the same chat.
    reply_to_message = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
    )

    # Media fields are meaningful only for IMAGE messages.
    media_visibility = models.CharField(
        max_length=10,
        choices=MediaVisibility.choices,
        default=MediaVisibility.NORMAL,
    )
    viewed_at = models.DateTimeField(null=True, blank=True)
    media_expires_at = models.DateTimeField(null=True, blank=True)
    media_status = models.CharField(
        max_length=10, choices=MediaStatus.choices, blank=True, default=""
    )

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = "messages"
        ordering = ["created_at"]
        indexes = [
            # Message list pagination within a chat, chronological.
            models.Index(
                fields=["chat", "created_at"], name="idx_message_chat_created"
            ),
            # Media cleanup task: available images past their expiry.
            models.Index(
                fields=["media_status", "media_expires_at"],
                name="idx_message_media_expiry",
            ),
        ]

    def __str__(self) -> str:
        return f"Message<{self.id}> chat={self.chat_id} {self.message_type}"
