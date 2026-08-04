"""
Chat lifecycle service.

Owns ``chats`` and ``chat_participants``. Centralizes every chat state
transition (create, expire, extend, reveal, end, leave, hide) and the
read-only/writable rules. All transitions row-lock the chat so concurrent
callers (e.g. two payment webhooks, or the expiry job racing a reveal) cannot
corrupt the state machine.

Per the frozen source of truth, expiry sets status=EXPIRED while the phase stays
ANONYMOUS — there is no POST_EXPIRY phase.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.chats.constants import (
    CHAT_ANONYMOUS_WINDOW_HOURS,
    CHAT_EXTENSION_WINDOW_HOURS,
)
from apps.chats.enums import (
    ChatPhase,
    ChatStatus,
    EndReason,
    JoinedVia,
    ParticipantStatus,
)
from apps.chats.models import Chat, ChatParticipant
from apps.common.realtime import broadcast_to_chat
from apps.common.results import ServiceResult
from apps.users.models import User

logger = logging.getLogger(__name__)


def _resolve_window(override_seconds: int, default_hours: int) -> timedelta:
    """Chat window duration, honoring the dev time-compression override.

    Returns the frozen ``default_hours`` unless a positive seconds override is
    configured (local dev only), in which case the compressed value is used.
    """
    if override_seconds and override_seconds > 0:
        return timedelta(seconds=override_seconds)
    return timedelta(hours=default_hours)


class ChatService:
    """Chat lifecycle and participant management."""

    # Statuses in which a chat is ongoing (the user is actively in it).
    ONGOING_STATUSES = (ChatStatus.ACTIVE, ChatStatus.EXTENDED, ChatStatus.REVEALED)
    # Statuses in which messages may still be written.
    WRITABLE_STATUSES = ONGOING_STATUSES

    def __init__(self, *, notification_service=None) -> None:
        # Imported lazily to avoid a hard import at module load; injectable for
        # tests.
        if notification_service is None:
            from apps.notifications.services.notification_service import (
                NotificationService,
            )

            notification_service = NotificationService()
        self._notifications = notification_service

    # -- Queries ------------------------------------------------------------

    def get_chat(self, chat_id: str) -> Chat | None:
        return Chat.objects.filter(id=chat_id).first()

    def get_active_chat(self, user: User) -> Chat | None:
        """Return the user's single ongoing chat, if any."""
        participant = (
            ChatParticipant.objects.select_related("chat")
            .filter(
                user=user,
                status=ParticipantStatus.ACTIVE,
                chat__status__in=self.ONGOING_STATUSES,
            )
            .first()
        )
        return participant.chat if participant else None

    def has_active_chat(self, user: User) -> bool:
        """Whether the user is currently in an ongoing chat (the 1-chat rule)."""
        return ChatParticipant.objects.filter(
            user=user,
            status=ParticipantStatus.ACTIVE,
            chat__status__in=self.ONGOING_STATUSES,
        ).exists()

    def get_participant(self, chat: Chat, user: User) -> ChatParticipant | None:
        return ChatParticipant.objects.filter(chat=chat, user=user).first()

    def is_participant(self, chat: Chat, user: User) -> bool:
        return ChatParticipant.objects.filter(chat=chat, user=user).exists()

    def is_writable(self, chat: Chat) -> bool:
        return chat.status in self.WRITABLE_STATUSES

    # -- Read receipts ------------------------------------------------------

    def mark_read(
        self, *, user: User, chat_id: str, last_read_message_id: str
    ) -> ServiceResult[ChatParticipant]:
        """Advance a participant's read pointer to a message in the chat.

        ChatService owns chat_participants, so the read-state pointer lives here
        rather than in MessageService. The target message is validated to belong
        to the chat to reject spoofed pointers.
        """
        from apps.messaging.models import Message

        chat = self.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        participant = self.get_participant(chat, user)
        if participant is None:
            return ServiceResult.fail(
                "FORBIDDEN", "You are not a participant of this chat."
            )
        if not Message.objects.filter(id=last_read_message_id, chat=chat).exists():
            return ServiceResult.fail(
                "VALIDATION_ERROR", "Message does not belong to this chat."
            )

        participant.last_read_message_id = last_read_message_id
        participant.last_read_at = timezone.now()
        participant.save(update_fields=["last_read_message_id", "last_read_at"])
        # Read receipt goes to the other participant only.
        reader_id, last_read = user.id, str(last_read_message_id)
        transaction.on_commit(
            lambda: broadcast_to_chat(
                chat_id,
                "chat.read",
                {"user_id": str(reader_id), "last_read_message_id": last_read},
                exclude_user_id=reader_id,
            )
        )
        return ServiceResult.ok(participant)

    # -- Creation -----------------------------------------------------------

    @transaction.atomic
    def create_chat(self, user_a: User, user_b: User) -> ServiceResult[Chat]:
        """Create an anonymous chat between two distinct users.

        Guards the one-active-chat-per-user rule defensively (the matchmaker
        already checks it, but this service is the authority on chat state).
        """
        if user_a.id == user_b.id:
            return ServiceResult.fail(
                "VALIDATION_ERROR", "Cannot create a chat with a single user."
            )
        if self.has_active_chat(user_a) or self.has_active_chat(user_b):
            return ServiceResult.fail(
                "CONFLICT", "One of the users is already in an active chat."
            )

        now = timezone.now()
        chat = Chat.objects.create(
            status=ChatStatus.ACTIVE,
            current_phase=ChatPhase.ANONYMOUS,
            status_changed_at=now,
            current_phase_ends_at=now
            + _resolve_window(
                settings.CHAT_ANONYMOUS_WINDOW_SECONDS_OVERRIDE,
                CHAT_ANONYMOUS_WINDOW_HOURS,
            ),
        )
        ChatParticipant.objects.bulk_create(
            [
                ChatParticipant(chat=chat, user=user_a, joined_via=JoinedVia.MATCH),
                ChatParticipant(chat=chat, user=user_b, joined_via=JoinedVia.MATCH),
            ]
        )
        logger.info(
            "Chat %s created for users %s and %s", chat.id, user_a.id, user_b.id
        )
        return ServiceResult.ok(chat)

    # -- Message accounting -------------------------------------------------

    def record_new_message(self, chat: Chat, *, sent_at: datetime) -> None:
        """Atomically bump the chat's message count and last-message timestamp.

        Uses an F() expression so concurrent sends increment correctly without
        a read-modify-write race. Called by MessageService.
        """
        Chat.objects.filter(id=chat.id).update(
            message_count=F("message_count") + 1,
            last_message_at=sent_at,
        )

    # -- Transitions --------------------------------------------------------

    def expire_chat(self, chat_id: str) -> ServiceResult[Chat]:
        """Transition an anonymous chat to EXPIRED when its window ends.

        Idempotent: a chat that is no longer ACTIVE/EXTENDED is returned
        unchanged so the batch expiry job can run safely.
        """
        with transaction.atomic():
            chat = Chat.objects.select_for_update().filter(id=chat_id).first()
            if chat is None:
                return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
            if chat.status not in (ChatStatus.ACTIVE, ChatStatus.EXTENDED):
                return ServiceResult.ok(chat)

            now = timezone.now()
            old_status = chat.status
            chat.status = ChatStatus.EXPIRED
            # Phase stays ANONYMOUS: identity was never revealed (frozen rule).
            chat.status_changed_at = now
            chat.save(update_fields=["status", "status_changed_at"])
            self._broadcast_state_change(chat.id, old_status, ChatStatus.EXPIRED)

        self._notify_participants(
            chat,
            notification_type="chat.expired",
            title="Your anonymous chat has ended",
            body="Reveal, extend, or exit the conversation.",
        )
        logger.info("Chat %s expired.", chat.id)
        return ServiceResult.ok(chat)

    def extend_chat(self, chat_id: str) -> ServiceResult[Chat]:
        """Grant a paid anonymous extension: reactivate as EXTENDED."""
        with transaction.atomic():
            chat = Chat.objects.select_for_update().filter(id=chat_id).first()
            if chat is None:
                return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
            if chat.status in (ChatStatus.ENDED, ChatStatus.REVEALED):
                return ServiceResult.fail(
                    "CONFLICT", "Chat cannot be extended in its current state."
                )
            now = timezone.now()
            old_status = chat.status
            chat.status = ChatStatus.EXTENDED
            chat.status_changed_at = now
            chat.current_phase_ends_at = now + _resolve_window(
                settings.CHAT_EXTENSION_WINDOW_SECONDS_OVERRIDE,
                CHAT_EXTENSION_WINDOW_HOURS,
            )
            chat.anonymous_chat_extension_count = (
                F("anonymous_chat_extension_count") + 1
            )
            chat.save(
                update_fields=[
                    "status",
                    "status_changed_at",
                    "current_phase_ends_at",
                    "anonymous_chat_extension_count",
                ]
            )
            self._broadcast_state_change(chat.id, old_status, ChatStatus.EXTENDED)
        chat.refresh_from_db(fields=["anonymous_chat_extension_count"])
        logger.info("Chat %s extended.", chat.id)
        return ServiceResult.ok(chat)

    def mark_revealed(self, chat_id: str) -> ServiceResult[Chat]:
        """Transition to REVEALED once both users have paid to reveal."""
        with transaction.atomic():
            chat = Chat.objects.select_for_update().filter(id=chat_id).first()
            if chat is None:
                return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
            if chat.status == ChatStatus.REVEALED:
                return ServiceResult.ok(chat)  # Idempotent.
            if chat.status == ChatStatus.ENDED:
                return ServiceResult.fail(
                    "CONFLICT", "Chat has ended and cannot be revealed."
                )
            now = timezone.now()
            old_status = chat.status
            chat.status = ChatStatus.REVEALED
            chat.current_phase = ChatPhase.REVEALED
            chat.status_changed_at = now
            chat.save(update_fields=["status", "current_phase", "status_changed_at"])
            self._broadcast_state_change(chat.id, old_status, ChatStatus.REVEALED)
        logger.info("Chat %s revealed.", chat.id)
        return ServiceResult.ok(chat)

    def end_chat(self, chat_id: str, *, reason: EndReason | str) -> ServiceResult[Chat]:
        """End a chat (read-only thereafter). Idempotent if already ended."""
        with transaction.atomic():
            chat = Chat.objects.select_for_update().filter(id=chat_id).first()
            if chat is None:
                return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
            if chat.status == ChatStatus.ENDED:
                return ServiceResult.ok(chat)
            now = timezone.now()
            old_status = chat.status
            chat.status = ChatStatus.ENDED
            chat.end_reason = reason
            chat.ended_at = now
            chat.status_changed_at = now
            chat.save(
                update_fields=["status", "end_reason", "ended_at", "status_changed_at"]
            )
            self._broadcast_state_change(chat.id, old_status, ChatStatus.ENDED)
        logger.info("Chat %s ended (%s).", chat.id, reason)
        return ServiceResult.ok(chat)

    def leave_chat(self, *, user: User, chat_id: str) -> ServiceResult[Chat]:
        """A participant exits: mark them LEFT and end the conversation."""
        chat = self.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        participant = self.get_participant(chat, user)
        if participant is None:
            return ServiceResult.fail(
                "FORBIDDEN", "You are not a participant of this chat."
            )
        if participant.status != ParticipantStatus.LEFT:
            participant.status = ParticipantStatus.LEFT
            participant.left_at = timezone.now()
            participant.save(update_fields=["status", "left_at"])
        return self.end_chat(chat_id, reason=EndReason.USER_EXIT)

    def hide_chat(self, *, user: User, chat_id: str) -> ServiceResult[ChatParticipant]:
        """Hide a chat from the user's list without affecting the other user."""
        chat = self.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        participant = self.get_participant(chat, user)
        if participant is None:
            return ServiceResult.fail(
                "FORBIDDEN", "You are not a participant of this chat."
            )
        if not participant.is_chat_hidden:
            participant.is_chat_hidden = True
            participant.hidden_at = timezone.now()
            participant.save(update_fields=["is_chat_hidden", "hidden_at"])
        return ServiceResult.ok(participant)

    # -- Internal helpers ---------------------------------------------------

    def _broadcast_state_change(
        self, chat_id, old_status: str, new_status: str
    ) -> None:
        """Broadcast chat.state_updated after the transition commits."""
        if old_status == new_status:
            return
        cid = str(chat_id)
        transaction.on_commit(
            lambda: broadcast_to_chat(
                cid,
                "chat.state_updated",
                {
                    "chat_id": cid,
                    "old_status": old_status,
                    "new_status": new_status,
                },
            )
        )

    def _notify_participants(
        self, chat: Chat, *, notification_type: str, title: str, body: str
    ) -> None:
        participants = ChatParticipant.objects.select_related("user").filter(chat=chat)
        for participant in participants:
            self._notifications.create_notification(
                user=participant.user,
                type=notification_type,
                title=title,
                body=body,
                action_type="OPEN_CHAT",
                action_payload={"chat_id": str(chat.id)},
            )
