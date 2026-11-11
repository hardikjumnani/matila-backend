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

    # Client-minted idempotency key for at-least-once send dedup. Device-unique
    # only (format "local_<micros>_<seq>"), so uniqueness is scoped per
    # (chat, sender). Empty for SYSTEM messages and any send without a key; the
    # unique constraint below is partial so those rows are exempt.
    client_message_id = models.CharField(max_length=128, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = "messages"
        ordering = ["created_at"]
        constraints = [
            # Idempotent sends: a retried POST/WS send reusing the same client id
            # must not create a second row. Partial so empty keys (SYSTEM, legacy,
            # keyless sends) never collide.
            models.UniqueConstraint(
                fields=["chat", "sender", "client_message_id"],
                condition=~models.Q(client_message_id=""),
                name="uniq_client_msg_per_sender_chat",
            ),
        ]
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
            # Veil cross-message window: a sender's last N messages in a chat
            # (newest first). Index-only scan for VeilService._build_window.
            models.Index(
                fields=["chat", "sender", "-created_at"],
                name="idx_message_chat_sender_dt",
            ),
        ]

    def __str__(self) -> str:
        return f"Message<{self.id}> chat={self.chat_id} {self.message_type}"


class MessageReaction(UUIDModel):
    """One emoji reaction by a user on a message. The unique (message, user)
    constraint enforces one reaction per user per message: re-reacting with a
    different emoji UPDATEs the row (replace), the same emoji is removed via
    DELETE. Emoji is validated against the runtime ``reaction_emojis`` set."""

    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="message_reactions",
    )
    emoji = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "message_reactions"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "user"], name="uniq_reaction_per_user_message"
            ),
        ]
        indexes = [
            models.Index(fields=["message"], name="idx_reaction_message"),
        ]

    def __str__(self) -> str:
        return f"MessageReaction<{self.id}> msg={self.message_id} {self.emoji}"
