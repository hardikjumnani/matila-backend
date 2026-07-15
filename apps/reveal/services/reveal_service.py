"""
Reveal service.

Owns ``reveal_intents``. Each participant expresses reveal intent independently
(no accept/decline, and the initiator is never disclosed). Once both have
expressed intent and both have paid, the reveal completes and ChatService flips
the chat to REVEALED.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.chats.enums import ChatStatus
from apps.common.results import ServiceResult
from apps.configuration.constants import FeatureFlagKey
from apps.reveal.constants import (
    REVEAL_ELIGIBILITY_HOURS,
    REVEAL_ELIGIBILITY_MESSAGE_COUNT,
)
from apps.reveal.enums import RevealIntentStatus, RevealTriggerType
from apps.reveal.models import RevealIntent
from apps.users.models import User

logger = logging.getLogger(__name__)

# Intent states that count as an active expression of reveal intent.
_ACTIVE_INTENT_STATES = (
    RevealIntentStatus.PENDING,
    RevealIntentStatus.PAID,
    RevealIntentStatus.COMPLETED,
)


class RevealService:
    """Reveal intent, mutual detection, and completion."""

    def __init__(
        self,
        *,
        chat_service=None,
        configuration_service=None,
        notification_service=None,
    ) -> None:
        if chat_service is None:
            from apps.chats.services.chat_service import ChatService

            chat_service = ChatService()
        if configuration_service is None:
            from apps.configuration.services.configuration_service import (
                ConfigurationService,
            )

            configuration_service = ConfigurationService()
        if notification_service is None:
            from apps.notifications.services.notification_service import (
                NotificationService,
            )

            notification_service = NotificationService()
        self._chats = chat_service
        self._config = configuration_service
        self._notifications = notification_service

    # -- Eligibility --------------------------------------------------------

    def is_eligible(self, chat) -> bool:
        """Reveal is available after 24h OR 100 exchanged messages (frozen)."""
        by_time = timezone.now() - chat.created_at >= timedelta(
            hours=REVEAL_ELIGIBILITY_HOURS
        )
        by_count = chat.message_count >= REVEAL_ELIGIBILITY_MESSAGE_COUNT
        return by_time or by_count

    def get_eligibility(self, *, chat_id: str) -> ServiceResult[dict]:
        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        return ServiceResult.ok(
            {
                "eligible": self.is_eligible(chat),
                "message_count": chat.message_count,
                "eligibility_message_count": REVEAL_ELIGIBILITY_MESSAGE_COUNT,
                "eligibility_hours": REVEAL_ELIGIBILITY_HOURS,
            }
        )

    # -- Intent -------------------------------------------------------------

    def submit_intent(
        self,
        *,
        chat_id: str,
        user: User,
        trigger_type: RevealTriggerType | str = RevealTriggerType.MANUAL,
    ) -> ServiceResult[dict]:
        """Record a participant's independent reveal intent (idempotent)."""
        if not self._config.is_feature_enabled(FeatureFlagKey.REVEAL_ENABLED):
            return ServiceResult.fail("FORBIDDEN", "Reveal is currently disabled.")

        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        if not self._chats.is_participant(chat, user):
            return ServiceResult.fail("FORBIDDEN", "You are not in this chat.")
        if chat.status == ChatStatus.REVEALED:
            return ServiceResult.fail("CONFLICT", "This chat is already revealed.")
        if chat.status == ChatStatus.ENDED:
            return ServiceResult.fail("CONFLICT", "This chat has ended.")
        if not self.is_eligible(chat):
            return ServiceResult.fail(
                "VALIDATION_ERROR", "Reveal is not yet available for this chat."
            )

        with transaction.atomic():
            intent, created = RevealIntent.objects.select_for_update().get_or_create(
                chat=chat,
                user=user,
                defaults={
                    "status": RevealIntentStatus.PENDING,
                    "trigger_type": trigger_type,
                },
            )
            mutual = self._is_mutual(chat_id)

        if mutual and created:
            # Both sides now want to reveal; notify equally (initiator not named).
            self._notify_mutual(chat_id)

        payment_required = mutual and chat.status != ChatStatus.REVEALED
        return ServiceResult.ok(
            {
                "status": intent.status,
                "mutual": mutual,
                "payment_required": payment_required,
            }
        )

    def get_status(self, *, chat_id: str, user: User) -> ServiceResult[dict]:
        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        intent = RevealIntent.objects.filter(chat_id=chat_id, user=user).first()
        mutual = self._is_mutual(chat_id)
        return ServiceResult.ok(
            {
                "my_intent_status": intent.status if intent else None,
                "mutual": mutual,
                "payment_required": mutual and chat.status != ChatStatus.REVEALED,
                "is_revealed": chat.status == ChatStatus.REVEALED,
            }
        )

    def is_mutual(self, chat_id: str) -> bool:
        return self._is_mutual(chat_id)

    # -- Payment-driven progression ----------------------------------------

    def mark_intent_paid(self, *, chat_id: str, user: User) -> ServiceResult[dict]:
        """Mark a user's reveal intent PAID; complete the reveal if both paid."""
        with transaction.atomic():
            intent = (
                RevealIntent.objects.select_for_update()
                .filter(chat_id=chat_id, user=user)
                .first()
            )
            if intent is None:
                return ServiceResult.fail(
                    "VALIDATION_ERROR", "No reveal intent to mark paid."
                )
            if intent.status == RevealIntentStatus.PENDING:
                intent.status = RevealIntentStatus.PAID
                intent.status_changed_at = timezone.now()
                intent.save(update_fields=["status", "status_changed_at"])

            both_paid = not RevealIntent.objects.filter(chat_id=chat_id).exclude(
                status__in=(RevealIntentStatus.PAID, RevealIntentStatus.COMPLETED)
            ).exists() and (RevealIntent.objects.filter(chat_id=chat_id).count() == 2)

        if both_paid:
            return self.complete_reveal(chat_id=chat_id)
        return ServiceResult.ok({"completed": False})

    def complete_reveal(self, *, chat_id: str) -> ServiceResult[dict]:
        """Finalize a mutual, fully-paid reveal (idempotent)."""
        result = self._chats.mark_revealed(chat_id)
        if result.failed:
            return ServiceResult.fail(result.error_code, result.error_message)

        RevealIntent.objects.filter(chat_id=chat_id).update(
            status=RevealIntentStatus.COMPLETED, status_changed_at=timezone.now()
        )
        self._notify_revealed(chat_id)
        logger.info("Reveal completed for chat %s", chat_id)
        return ServiceResult.ok({"completed": True})

    # -- Internal -----------------------------------------------------------

    def _is_mutual(self, chat_id: str) -> bool:
        """Both participants have an active reveal intent."""
        return (
            RevealIntent.objects.filter(
                chat_id=chat_id, status__in=_ACTIVE_INTENT_STATES
            ).count()
            >= 2
        )

    def _notify_mutual(self, chat_id: str) -> None:
        for user in self._participant_users(chat_id):
            self._notifications.create_notification(
                user=user,
                type="reveal.available",
                title="Reveal is available",
                body="Both of you want to reveal. Complete payment to continue.",
                action_type="OPEN_CHAT",
                action_payload={"chat_id": str(chat_id)},
            )

    def _notify_revealed(self, chat_id: str) -> None:
        for user in self._participant_users(chat_id):
            self._notifications.create_notification(
                user=user,
                type="reveal.completed",
                title="Identities revealed!",
                body="You can now see each other.",
                action_type="OPEN_CHAT",
                action_payload={"chat_id": str(chat_id)},
            )

    def _participant_users(self, chat_id: str):
        from apps.chats.models import ChatParticipant

        return [
            participant.user
            for participant in ChatParticipant.objects.select_related("user").filter(
                chat_id=chat_id
            )
        ]
