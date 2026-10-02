"""
Matchmaking service.

Owns ``match_queue`` and creates chats (via ChatService) on a successful match.

Matching is random within a compatible bucket, using hard filters on intent and
mutual gender preference. Candidate rows are locked with ``FOR UPDATE SKIP
LOCKED`` so two concurrent joins can never pair the same waiting user twice.

On a successful match both queue entries are deleted (the queue is ephemeral and
has no "matched" status); the resulting chat is the record of truth, and the
waiting user learns of the match via a notification and the status endpoint.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat, ChatParticipant
from apps.common.results import ServiceResult
from apps.matchmaking.constants import LOBBY_BUCKET_SIZE
from apps.matchmaking.enums import MatchQueueStatus
from apps.matchmaking.models import MatchQueue
from apps.users.enums import AccountStatus, Intent, VerificationStatus
from apps.users.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class JoinResult:
    matched: bool
    chat: Chat | None = None
    queue_entry: MatchQueue | None = None


class MatchmakingService:
    """Queue management and random compatible matching."""

    def __init__(
        self,
        *,
        chat_service=None,
        notification_service=None,
        presence_service=None,
    ) -> None:
        if chat_service is None:
            from apps.chats.services.chat_service import ChatService

            chat_service = ChatService()
        if notification_service is None:
            from apps.notifications.services.notification_service import (
                NotificationService,
            )

            notification_service = NotificationService()
        if presence_service is None:
            from apps.matchmaking.services.presence_service import PresenceService

            presence_service = PresenceService()
        self._chats = chat_service
        self._notifications = notification_service
        self._presence = presence_service

    # -- Eligibility --------------------------------------------------------

    def _check_eligibility(self, user: User) -> ServiceResult[None]:
        if user.onboarding_completed_at is None:
            return ServiceResult.fail(
                "ONBOARDING_INCOMPLETE", "Complete onboarding before matchmaking."
            )
        if user.verification_status != VerificationStatus.APPROVED:
            return ServiceResult.fail(
                "VERIFICATION_REQUIRED", "Your account must be verified."
            )
        return ServiceResult.ok(None)

    # -- Join / leave / heartbeat ------------------------------------------

    def join(self, user: User) -> ServiceResult[JoinResult]:
        """Join the queue and attempt an immediate match. Idempotent."""
        eligibility = self._check_eligibility(user)
        if eligibility.failed:
            return ServiceResult.fail(eligibility.error_code, eligibility.error_message)
        if self._chats.has_active_chat(user):
            return ServiceResult.fail("CONFLICT", "You are already in an active chat.")

        with transaction.atomic():
            entry = (
                MatchQueue.objects.select_for_update()
                .filter(user=user, status=MatchQueueStatus.SEARCHING)
                .first()
            )
            if entry is None:
                entry = MatchQueue.objects.create(
                    user=user,
                    intent=user.intent,
                    gender_preferences=user.gender_preferences,
                    is_online=True,
                    last_heartbeat_at=timezone.now(),
                )
            match = self._attempt_match(user, entry)

        if match is not None:
            chat, partner = match
            self._notify_match(user, partner, chat)
            return ServiceResult.ok(JoinResult(matched=True, chat=chat))
        return ServiceResult.ok(JoinResult(matched=False, queue_entry=entry))

    def _attempt_match(self, user: User, entry: MatchQueue) -> tuple[Chat, User] | None:
        """Find and pair a compatible waiting user, if one exists.

        Runs inside the caller's transaction. Locks candidate queue rows with
        SKIP LOCKED so simultaneous matchers never contend for the same partner.
        """
        candidates = list(
            MatchQueue.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("user")
            .filter(status=MatchQueueStatus.SEARCHING, intent=user.intent)
            .exclude(user_id=user.id)
        )
        compatible = [c for c in candidates if self._is_compatible(user, entry, c)]
        if not compatible:
            return None

        partner_entry = secrets.choice(compatible)
        partner = partner_entry.user
        result = self._chats.create_chat(user, partner)
        if result.failed:
            # A partner became ineligible (e.g. already matched) between the
            # candidate scan and chat creation; treat as no match this round.
            logger.warning(
                "Chat creation failed during match of %s and %s: %s",
                user.id,
                partner.id,
                result.error_message,
            )
            return None

        MatchQueue.objects.filter(id__in=[entry.id, partner_entry.id]).delete()
        return result.data, partner

    def _is_compatible(
        self, user: User, entry: MatchQueue, candidate: MatchQueue
    ) -> bool:
        """Mutual gender-preference compatibility (intent already filtered)."""
        return self._gender_ok(
            candidate.user.gender, entry.gender_preferences
        ) and self._gender_ok(user.gender, candidate.gender_preferences)

    @staticmethod
    def _gender_ok(gender: str, preferences: list[str]) -> bool:
        # An empty preference list means "no restriction" (accept any gender).
        return not preferences or gender in preferences

    def leave(self, user: User) -> ServiceResult[None]:
        """Cancel the user's active queue entry (idempotent)."""
        updated = MatchQueue.objects.filter(
            user=user, status=MatchQueueStatus.SEARCHING
        ).update(status=MatchQueueStatus.CANCELLED, is_online=False)
        logger.info("User %s left the queue (%d entries).", user.id, updated)
        return ServiceResult.ok(None)

    def heartbeat(self, user: User) -> ServiceResult[None]:
        """Refresh queue presence for an actively searching user."""
        updated = MatchQueue.objects.filter(
            user=user, status=MatchQueueStatus.SEARCHING
        ).update(last_heartbeat_at=timezone.now(), is_online=True)
        if not updated:
            return ServiceResult.fail(
                "RESOURCE_NOT_FOUND", "No active queue entry to refresh."
            )
        return ServiceResult.ok(None)

    # -- Status / stats -----------------------------------------------------

    def get_status(self, user: User) -> dict:
        """Report the user's matchmaking state."""
        active_chat = self._chats.get_active_chat(user)
        if active_chat is not None:
            return {"state": "MATCHED", "chat_id": str(active_chat.id)}
        entry = MatchQueue.objects.filter(
            user=user, status=MatchQueueStatus.SEARCHING
        ).first()
        if entry is not None:
            return {
                "state": "SEARCHING",
                "queue_entry_id": str(entry.id),
                "joined_queue_at": entry.joined_queue_at,
            }
        return {"state": "IDLE"}

    @staticmethod
    def _plus_range(count: int) -> dict:
        """Coarse 'N+' range: floor to the nearest bucket. e.g. 27 -> {20, "20+"}."""
        floor = (count // LOBBY_BUCKET_SIZE) * LOBBY_BUCKET_SIZE
        return {"floor": floor, "label": f"{floor}+"}

    def _eligible_users(self):
        """Verified, active, onboarded users (the 'real' population)."""
        return User.objects.filter(
            verification_status=VerificationStatus.APPROVED,
            account_status=AccountStatus.ACTIVE,
            onboarding_completed_at__isnull=False,
        )

    def get_lobby_stats(self, user: User) -> dict:
        """Online counts for the slide-to-match screen, as 'N+' ranges:
        - total_online: everyone currently online (app foregrounded).
        - compatible_online: online users this person can actually match with
          (same intent, mutual gender compatibility, not self, not already in a
          chat)."""
        total_online = self._presence.online_count()
        online_ids = self._presence.online_ids()
        online_ids.discard(str(user.id))

        compatible = 0
        if online_ids:
            qs = self._eligible_users().filter(
                id__in=online_ids, intent=user.intent
            ).exclude(id=user.id)
            # Their gender must be one I accept (empty prefs = no restriction).
            if user.gender_preferences:
                qs = qs.filter(gender__in=user.gender_preferences)
            # My gender must be one they accept (empty prefs = no restriction).
            qs = qs.filter(
                Q(gender_preferences=[])
                | Q(gender_preferences__contains=[user.gender])
            )
            # Exclude anyone already in an ongoing chat (not available to match).
            busy_ids = ChatParticipant.objects.filter(
                chat__status__in=(
                    ChatStatus.ACTIVE,
                    ChatStatus.EXTENDED,
                    ChatStatus.REVEALED,
                )
            ).values_list("user_id", flat=True)
            compatible = qs.exclude(id__in=busy_ids).count()

        return {
            "total_online": self._plus_range(total_online),
            "compatible_online": self._plus_range(compatible),
        }

    def get_intent_stats(self) -> dict:
        """Per-intent counts (all intents), each as an 'N+' range — for the
        onboarding intent picker's social proof."""
        rows = (
            self._eligible_users().values("intent").annotate(c=Count("id"))
        )
        counts = {value: 0 for value in Intent.values}
        for row in rows:
            if row["intent"] in counts:
                counts[row["intent"]] = row["c"]
        return {intent: self._plus_range(c) for intent, c in counts.items()}

    # -- Maintenance (Step 8 task) -----------------------------------------

    def cleanup_stale(self, *, timeout_seconds: int) -> int:
        """Time out searching entries whose heartbeat has lapsed."""
        cutoff = timezone.now() - timedelta(seconds=timeout_seconds)
        return MatchQueue.objects.filter(
            status=MatchQueueStatus.SEARCHING, last_heartbeat_at__lt=cutoff
        ).update(status=MatchQueueStatus.TIMEOUT, is_online=False)

    # -- Internal -----------------------------------------------------------

    def _notify_match(self, user_a: User, user_b: User, chat: Chat) -> None:
        for participant in (user_a, user_b):
            self._notifications.create_notification(
                user=participant,
                type="match.found",
                title="You've been matched!",
                body="Start your anonymous chat.",
                action_type="OPEN_CHAT",
                action_payload={"chat_id": str(chat.id)},
            )
