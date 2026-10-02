"""
Message service.

Owns ``messages``. Validates that a chat is writable and that the sender is a
participant, then persists messages and maintains the chat's message accounting
(via ChatService). Handles replies, view-once media lifecycle, image uploads,
soft deletion, and system messages.

Messages are immutable (no edit) and deleted only softly. View-once media
becomes inaccessible once viewed; the S3 object is purged later by the cleanup
job (Step 8).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import BinaryIO

from django.db import transaction
from django.utils import timezone

from apps.common.realtime import broadcast_to_chat
from apps.common.results import ServiceResult
from apps.configuration.constants import FeatureFlagKey
from apps.messaging.constants import MAX_TEXT_MESSAGE_LENGTH, MEDIA_RETENTION_DAYS
from apps.messaging.enums import MediaStatus, MediaVisibility, MessageType
from apps.messaging.models import Message
from apps.messaging.realtime import build_message_payload
from apps.users.models import User

logger = logging.getLogger(__name__)

_IMAGE_KEY_PREFIX = "chat/images"


class MessageService:
    """Message creation, view-once media, and read/delete state."""

    def __init__(
        self, *, chat_service=None, storage_service=None, configuration_service=None
    ) -> None:
        if chat_service is None:
            from apps.chats.services.chat_service import ChatService

            chat_service = ChatService()
        if storage_service is None:
            from apps.common.services.storage_service import StorageService

            storage_service = StorageService()
        if configuration_service is None:
            from apps.configuration.services.configuration_service import (
                ConfigurationService,
            )

            configuration_service = ConfigurationService()
        self._chats = chat_service
        self._storage = storage_service
        self._config = configuration_service

    # -- Queries ------------------------------------------------------------

    def get_message(self, message_id: str) -> Message | None:
        return Message.objects.filter(id=message_id).select_related("chat").first()

    def for_chat(self, chat):
        """Messages of a chat in chronological order (Step 6 paginates)."""
        return Message.objects.filter(chat=chat).order_by("created_at")

    # -- Sending ------------------------------------------------------------

    def send_text(
        self,
        *,
        chat_id: str,
        sender: User,
        content: str,
        reply_to_message_id: str | None = None,
    ) -> ServiceResult[Message]:
        chat, error = self._resolve_writable_chat(chat_id, sender)
        if error is not None:
            return error

        content = (content or "").strip()
        if not content:
            return ServiceResult.fail("VALIDATION_ERROR", "Message content is empty.")
        if len(content) > MAX_TEXT_MESSAGE_LENGTH:
            return ServiceResult.fail(
                "MESSAGE_TOO_LONG",
                f"Message exceeds {MAX_TEXT_MESSAGE_LENGTH} characters.",
            )

        reply = None
        if reply_to_message_id:
            reply = Message.objects.filter(
                id=reply_to_message_id, chat=chat, is_deleted=False
            ).first()
            if reply is None:
                return ServiceResult.fail(
                    "INVALID_REPLY_TARGET", "The message being replied to is invalid."
                )

        message = Message.objects.create(
            chat=chat,
            sender=sender,
            message_type=MessageType.TEXT,
            text_content=content,
            reply_to_message=reply,
        )
        self._chats.record_new_message(chat, sent_at=message.created_at)
        self._broadcast_new_message(message)
        return ServiceResult.ok(message)

    def send_image(
        self,
        *,
        chat_id: str,
        sender: User,
        fileobj: BinaryIO,
        filename: str,
        content_type: str,
        visibility: MediaVisibility | str = MediaVisibility.NORMAL,
        reply_to_message_id: str | None = None,
    ) -> ServiceResult[Message]:
        if not self._config.is_feature_enabled(FeatureFlagKey.IMAGE_MESSAGES_ENABLED):
            return ServiceResult.fail(
                "FORBIDDEN", "Image messages are currently disabled."
            )

        chat, error = self._resolve_writable_chat(chat_id, sender)
        if error is not None:
            return error

        reply = None
        if reply_to_message_id:
            reply = Message.objects.filter(
                id=reply_to_message_id, chat=chat, is_deleted=False
            ).first()
            if reply is None:
                return ServiceResult.fail(
                    "INVALID_REPLY_TARGET", "The message being replied to is invalid."
                )

        key = self._storage.build_key(_IMAGE_KEY_PREFIX, filename)
        self._storage.upload_fileobj(fileobj, key, content_type=content_type)

        message = Message.objects.create(
            chat=chat,
            sender=sender,
            message_type=MessageType.IMAGE,
            media_url=key,
            media_visibility=visibility,
            media_status=MediaStatus.AVAILABLE,
            media_expires_at=timezone.now() + timedelta(days=MEDIA_RETENTION_DAYS),
            reply_to_message=reply,
        )
        self._chats.record_new_message(chat, sent_at=message.created_at)
        self._broadcast_new_message(message)
        return ServiceResult.ok(message)

    def create_system_message(
        self, *, chat, content: str, metadata: dict | None = None
    ) -> Message:
        """Create a SYSTEM message. System messages do not count toward the
        exchanged-message total that governs reveal eligibility."""
        return Message.objects.create(
            chat=chat,
            sender=None,
            message_type=MessageType.SYSTEM,
            text_content=content,
            metadata=metadata or {},
        )

    # -- View-once media ----------------------------------------------------

    def view_once(
        self, *, message_id: str, user: User
    ) -> ServiceResult[tuple[bytes, str]]:
        """Consume a view-once image EXACTLY ONCE and return its bytes + content
        type for server-mediated, one-time delivery.

        Security model (see docs/VIEW_ONCE_HARDENING.md): the media URL is never
        exposed in any payload; the recipient fetches the bytes only through this
        call. The AVAILABLE→VIEWED transition is row-locked so concurrent taps
        can't double-consume, and the blob is deleted immediately after so a
        captured request can't be replayed.
        """
        key: str | None = None
        with transaction.atomic():
            message = (
                Message.objects.select_for_update()
                .select_related("chat")
                .filter(id=message_id)
                .first()
            )
            if message is None:
                return ServiceResult.fail("RESOURCE_NOT_FOUND", "Message not found.")
            if (
                message.message_type != MessageType.IMAGE
                or message.media_visibility != MediaVisibility.VIEW_ONCE
            ):
                return ServiceResult.fail(
                    "VALIDATION_ERROR", "Message is not view-once media."
                )
            if not self._chats.is_participant(message.chat, user):
                return ServiceResult.fail("FORBIDDEN", "You are not in this chat.")
            if message.sender_id == user.id:
                return ServiceResult.fail(
                    "FORBIDDEN", "The sender cannot view their own view-once media."
                )
            if message.media_status != MediaStatus.AVAILABLE:
                return ServiceResult.fail(
                    "MEDIA_NOT_AVAILABLE", "This media is no longer available."
                )

            key = message.media_url
            message.viewed_at = timezone.now()
            message.media_status = MediaStatus.VIEWED
            message.save(update_fields=["viewed_at", "media_status"])
            # Notify the sender (not the viewer) that their media was consumed.
            chat_id, mid, viewer_id = str(message.chat_id), str(message.id), user.id
            transaction.on_commit(
                lambda: broadcast_to_chat(
                    chat_id,
                    "message.viewed",
                    {"message_id": mid},
                    exclude_user_id=viewer_id,
                )
            )

        # Consumed. Fetch the bytes, then destroy the blob so nothing is replayable.
        from apps.common.services.storage_service import StorageError

        try:
            data, content_type = self._storage.download_bytes(key)
        except StorageError:
            logger.error(
                "view-once download failed for message %s (already consumed)",
                message_id,
            )
            return ServiceResult.fail(
                "INTERNAL_SERVER_ERROR", "Could not load the media."
            )
        try:
            self._storage.delete_object(key)
        except Exception:  # noqa: BLE001 — best-effort; the view is already consumed.
            logger.warning("view-once blob delete failed for message %s", message_id)
        return ServiceResult.ok((data, content_type))

    # -- Deletion -----------------------------------------------------------

    def soft_delete(self, *, message_id: str, user: User) -> ServiceResult[Message]:
        """Soft-delete a message. Only the sender may delete their own message."""
        message = self.get_message(message_id)
        if message is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Message not found.")
        if message.sender_id != user.id:
            return ServiceResult.fail(
                "FORBIDDEN", "You can only delete your own messages."
            )
        if not message.is_deleted:
            message.is_deleted = True
            message.deleted_at = timezone.now()
            message.save(update_fields=["is_deleted", "deleted_at"])
            chat_id, message_id = str(message.chat_id), str(message.id)
            transaction.on_commit(
                lambda: broadcast_to_chat(
                    chat_id, "message.deleted", {"message_id": message_id}
                )
            )
        return ServiceResult.ok(message)

    # -- Internal -----------------------------------------------------------

    def _broadcast_new_message(self, message: Message) -> None:
        """Broadcast message.new to the chat group after the row commits.

        Emitted here (not in the transport layer) so both REST and WebSocket
        sends deliver the message in real time exactly once, and only after the
        database transaction has committed.
        """
        payload = {"message": build_message_payload(message)}
        chat_id = str(message.chat_id)
        transaction.on_commit(
            lambda: broadcast_to_chat(chat_id, "message.new", payload)
        )

    def _resolve_writable_chat(
        self, chat_id: str, sender: User
    ) -> tuple[object, ServiceResult | None]:
        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return None, ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        if not self._chats.is_participant(chat, sender):
            return None, ServiceResult.fail(
                "FORBIDDEN", "You are not a participant of this chat."
            )
        if not self._chats.is_writable(chat):
            return None, ServiceResult.fail(
                "CHAT_READ_ONLY", "This chat no longer accepts messages."
            )
        return chat, None
