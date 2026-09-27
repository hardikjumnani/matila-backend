"""
Reveal / decision service.

Owns the ``DecisionRound`` state machine: eligibility, the shared decision phase
(deterministic ``final_call``), payment-driven progression, the Safe Reveal
sub-phase, exits, and the 24h auto-exit. PaymentService records paid sides here;
ChatService creates the expiry round. See docs/REVEAL_FLOW_SPEC.md.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.chats.constants import DECISION_GRACE_HOURS
from apps.chats.enums import ChatStatus, EndReason
from apps.common.realtime import broadcast_to_chat
from apps.common.results import ServiceResult
from apps.configuration.constants import FeatureFlagKey
from apps.payments.enums import CoinLedgerReason, CoinType
from apps.reveal.constants import (
    REVEAL_ELIGIBILITY_MESSAGES_PER_USER,
    REVEAL_ELIGIBILITY_MINUTES,
)
from apps.reveal.enums import (
    TERMINAL_ROUND_PHASES,
    DecisionChoice,
    DecisionRoundPhase,
    FinalCall,
    RevealTrigger,
    SafeRevealDecision,
)
from apps.reveal.models import DecisionRound, ParticipantDecision
from apps.users.enums import Gender
from apps.users.models import User

logger = logging.getLogger(__name__)

# Which choices demand mutual payment (vs. the unilateral EXIT).
_PAYABLE = (DecisionChoice.REVEAL, DecisionChoice.SAFE_REVEAL, DecisionChoice.EXTEND)


class RevealService:
    """Decision-round state machine + reveal completion."""

    def __init__(
        self,
        *,
        chat_service=None,
        configuration_service=None,
        credit_service=None,
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
        if credit_service is None:
            from apps.payments.services.credit_service import CreditService

            credit_service = CreditService()
        if notification_service is None:
            from apps.notifications.services.notification_service import (
                NotificationService,
            )

            notification_service = NotificationService()
        self._chats = chat_service
        self._config = configuration_service
        self._credits = credit_service
        self._notifications = notification_service

    # -- Eligibility --------------------------------------------------------

    def is_eligible(self, chat) -> bool:
        """Reveal available after 5 min OR each user has sent >= 5 messages."""
        override = settings.REVEAL_ELIGIBILITY_SECONDS_OVERRIDE
        threshold = override or REVEAL_ELIGIBILITY_MINUTES * 60
        if timezone.now() - chat.created_at >= timedelta(seconds=threshold):
            return True
        from apps.messaging.models import Message

        counts = {
            row["sender"]: row["c"]
            for row in Message.objects.filter(chat=chat, sender__isnull=False)
            .values("sender")
            .annotate(c=models.Count("id"))
        }
        participant_ids = [p.user_id for p in chat.participants.all()]
        if len(participant_ids) < 2:
            return False
        return all(
            counts.get(uid, 0) >= REVEAL_ELIGIBILITY_MESSAGES_PER_USER
            for uid in participant_ids
        )

    def get_eligibility(self, *, chat_id: str) -> ServiceResult[dict]:
        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        return ServiceResult.ok(
            {
                "eligible": self.is_eligible(chat),
                "eligibility_minutes": REVEAL_ELIGIBILITY_MINUTES,
                "eligibility_messages_per_user": REVEAL_ELIGIBILITY_MESSAGES_PER_USER,
            }
        )

    # -- Choices & role -----------------------------------------------------

    def _safe_offered(self, chat, user: User) -> bool:
        """Safe Reveal is offered only to a FEMALE whose partner is MALE."""
        parts = list(chat.participants.select_related("user").all())
        if len(parts) != 2:
            return False
        me = next((p for p in parts if p.user_id == user.id), None)
        other = next((p for p in parts if p.user_id != user.id), None)
        if me is None or other is None:
            return False
        return me.user.gender == Gender.FEMALE and other.user.gender == Gender.MALE

    def available_choices(self, chat, user: User) -> list[str]:
        round_ = self._active_round(chat)
        if round_ is not None and round_.phase == DecisionRoundPhase.PAYMENT:
            return [DecisionChoice.EXIT]  # can only bail during payment
        if round_ is not None and round_.phase == DecisionRoundPhase.SAFE_DECISION:
            return []  # girl uses the safe-reveal endpoint; boy waits
        if chat.status in (ChatStatus.ACTIVE, ChatStatus.EXTENDED):
            base: list[str] = []
            if self.is_eligible(chat):
                base.append(DecisionChoice.REVEAL)
                if self._safe_offered(chat, user):
                    base.append(DecisionChoice.SAFE_REVEAL)
            base.append(DecisionChoice.EXIT)
            return base
        if chat.status == ChatStatus.EXPIRED:
            base = [DecisionChoice.REVEAL]
            if self._safe_offered(chat, user):
                base.append(DecisionChoice.SAFE_REVEAL)
            base += [DecisionChoice.EXTEND, DecisionChoice.EXIT]
            return base
        return []

    # -- Round accessors ----------------------------------------------------

    def _active_round(self, chat) -> DecisionRound | None:
        return (
            DecisionRound.objects.filter(chat=chat)
            .exclude(phase__in=TERMINAL_ROUND_PHASES)
            .order_by("-created_at")
            .first()
        )

    def _active_round_locked(self, chat) -> DecisionRound | None:
        return (
            DecisionRound.objects.select_for_update()
            .filter(chat=chat)
            .exclude(phase__in=TERMINAL_ROUND_PHASES)
            .order_by("-created_at")
            .first()
        )

    def _ensure_participant_rows(self, round_: DecisionRound, chat) -> None:
        for participant in chat.participants.all():
            ParticipantDecision.objects.get_or_create(
                round=round_, user_id=participant.user_id
            )

    def _get_or_create_round_locked(self, chat) -> DecisionRound:
        round_ = self._active_round_locked(chat)
        if round_ is None:
            trigger = (
                RevealTrigger.EXPIRY
                if chat.status == ChatStatus.EXPIRED
                else RevealTrigger.MID_CHAT
            )
            round_ = DecisionRound.objects.create(
                chat=chat,
                trigger=trigger,
                phase=DecisionRoundPhase.DECISION,
                decision_deadline_at=(
                    chat.decision_deadline_at
                    if trigger == RevealTrigger.EXPIRY
                    else None
                ),
            )
            self._ensure_participant_rows(round_, chat)
        return round_

    def create_expiry_round(self, chat) -> DecisionRound:
        """Called by ChatService on expiry: fresh EXPIRY round + 24h deadline.

        Cancels an active DECISION-phase round (choices discarded); leaves a
        round already in PAYMENT/SAFE_DECISION to resolve on its own.
        """
        existing = self._active_round_locked(chat)
        if existing is not None:
            if existing.phase == DecisionRoundPhase.DECISION:
                existing.phase = DecisionRoundPhase.CANCELLED
                existing.save(update_fields=["phase", "status_changed_at"])
            else:
                return existing
        round_ = DecisionRound.objects.create(
            chat=chat,
            trigger=RevealTrigger.EXPIRY,
            phase=DecisionRoundPhase.DECISION,
            decision_deadline_at=chat.decision_deadline_at,
        )
        self._ensure_participant_rows(round_, chat)
        return round_

    # -- Decision submission ------------------------------------------------

    def submit_decision(
        self, *, chat_id: str, user: User, choice: str
    ) -> ServiceResult[dict]:
        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        if not self._chats.is_participant(chat, user):
            return ServiceResult.fail("FORBIDDEN", "You are not in this chat.")
        if chat.status in (ChatStatus.REVEALED, ChatStatus.ENDED):
            return ServiceResult.fail("CONFLICT", "This chat is already resolved.")
        if choice in (DecisionChoice.REVEAL, DecisionChoice.SAFE_REVEAL):
            if not self._config.is_feature_enabled(FeatureFlagKey.REVEAL_ENABLED):
                return ServiceResult.fail("FORBIDDEN", "Reveal is currently disabled.")
        if choice not in self.available_choices(chat, user):
            return ServiceResult.fail(
                "VALIDATION_ERROR", f"'{choice}' is not available right now."
            )

        with transaction.atomic():
            from apps.chats.models import Chat

            chat = Chat.objects.select_for_update().get(id=chat_id)
            if chat.status in (ChatStatus.REVEALED, ChatStatus.ENDED):
                return ServiceResult.fail("CONFLICT", "This chat is already resolved.")

            if choice == DecisionChoice.EXIT:
                round_ = self._get_or_create_round_locked(chat)
                return self._resolve_exit(round_, chat, exiting_user=user)

            round_ = self._get_or_create_round_locked(chat)
            if round_.phase != DecisionRoundPhase.DECISION:
                return ServiceResult.fail(
                    "CONFLICT", "A decision is already locked for this chat."
                )
            pd = (
                ParticipantDecision.objects.select_for_update()
                .get(round=round_, user=user)
            )
            pd.choice = choice
            pd.chosen_at = timezone.now()
            pd.save(update_fields=["choice", "chosen_at"])

            decisions = list(round_.decisions.select_related("user").all())
            both_chosen = all(d.choice for d in decisions)
            if both_chosen:
                round_.final_call = self._resolve_final_call(decisions)
                round_.phase = DecisionRoundPhase.PAYMENT
                round_.status_changed_at = timezone.now()
                round_.save(
                    update_fields=["final_call", "phase", "status_changed_at"]
                )

        # Post-commit signalling.
        if both_chosen:
            self._broadcast(
                chat_id,
                "decision.final_call",
                {"chat_id": str(chat_id), "final_call": round_.final_call},
            )
        else:
            # Tell the other participant this user is ready (mid-chat highlight).
            self._broadcast(
                chat_id,
                "decision.updated",
                {"chat_id": str(chat_id), "user_id": str(user.id), "choice": choice},
                exclude_user_id=str(user.id),
            )
            self._notify_ready(chat, exclude_user_id=user.id)
        return ServiceResult.ok(self._state_payload(chat_id, user))

    def _resolve_final_call(self, decisions) -> str:
        vals = [d.choice for d in decisions]
        if any(v == DecisionChoice.EXIT for v in vals):
            return FinalCall.EXIT
        if any(v == DecisionChoice.EXTEND for v in vals):
            return FinalCall.EXTEND
        if any(v == DecisionChoice.SAFE_REVEAL for v in vals):
            return FinalCall.SAFE_REVEAL
        if len(vals) == 2 and all(v == DecisionChoice.REVEAL for v in vals):
            return FinalCall.REVEAL
        return FinalCall.REVIEW

    # -- Payment-driven progression (called by PaymentService) --------------

    _PURPOSE_TO_FINAL = {
        "REVEAL": FinalCall.REVEAL,
        "SAFE_REVEAL": FinalCall.SAFE_REVEAL,
        "CHAT_EXTENSION": FinalCall.EXTEND,
    }

    def get_active_final_call(self, chat) -> str | None:
        round_ = self._active_round(chat)
        if round_ is None or round_.phase != DecisionRoundPhase.PAYMENT:
            return None
        return round_.final_call or None

    def active_round_id(self, chat) -> str | None:
        round_ = self._active_round(chat)
        return str(round_.id) if round_ else None

    def has_paid(self, chat, user: User) -> bool:
        round_ = self._active_round(chat)
        if round_ is None:
            return False
        pd = round_.decisions.filter(user=user).first()
        return bool(pd and pd.paid_at)

    def record_payment(
        self, *, chat_id: str, user: User, purpose: str, paid_with_coin: bool = False
    ) -> ServiceResult[dict]:
        """Mark this user's side paid on the active PAYMENT round; execute the
        final call once both sides have paid. Idempotent per side."""
        expected = self._PURPOSE_TO_FINAL.get(str(purpose))
        with transaction.atomic():
            from apps.chats.models import Chat

            chat = Chat.objects.select_for_update().get(id=chat_id)
            round_ = self._active_round_locked(chat)
            if round_ is None or round_.phase != DecisionRoundPhase.PAYMENT:
                return ServiceResult.ok({"applied": False})
            if expected is None or round_.final_call != expected:
                return ServiceResult.ok({"applied": False})

            pd = (
                ParticipantDecision.objects.select_for_update()
                .filter(round=round_, user=user)
                .first()
            )
            if pd is None:
                return ServiceResult.ok({"applied": False})
            if pd.paid_at is None:
                pd.paid_at = timezone.now()
                pd.paid_with_coin = paid_with_coin
                pd.save(update_fields=["paid_at", "paid_with_coin"])

            both_paid = all(d.paid_at for d in round_.decisions.all())
            if not both_paid:
                broadcast_side = True
                executed = None
            else:
                broadcast_side = False
                executed = self._execute_final_call(round_, chat)

        if both_paid:
            return executed or ServiceResult.ok({"applied": True, "both_paid": True})
        if broadcast_side:
            self._broadcast(
                chat_id,
                "payment.partner_paid",
                {"chat_id": str(chat_id), "user_id": str(user.id)},
                exclude_user_id=str(user.id),
            )
        return ServiceResult.ok({"applied": True, "both_paid": False})

    def _execute_final_call(self, round_: DecisionRound, chat) -> ServiceResult[dict]:
        fc = round_.final_call
        if fc == FinalCall.REVEAL:
            self._chats.mark_revealed(str(chat.id))
            round_.phase = DecisionRoundPhase.RESOLVED
            round_.status_changed_at = timezone.now()
            round_.save(update_fields=["phase", "status_changed_at"])
            transaction.on_commit(lambda: self._notify_revealed(chat.id))
            return ServiceResult.ok({"applied": True, "final_call": fc, "revealed": True})
        if fc == FinalCall.EXTEND:
            self._chats.extend_chat(str(chat.id))
            round_.phase = DecisionRoundPhase.RESOLVED
            round_.status_changed_at = timezone.now()
            round_.save(update_fields=["phase", "status_changed_at"])
            transaction.on_commit(lambda: self._notify_extended(chat.id))
            return ServiceResult.ok({"applied": True, "final_call": fc, "extended": True})
        if fc == FinalCall.SAFE_REVEAL:
            return self._enter_safe_decision(round_, chat)
        return ServiceResult.ok({"applied": True, "final_call": fc})

    def _enter_safe_decision(self, round_: DecisionRound, chat) -> ServiceResult[dict]:
        now = timezone.now()
        round_.phase = DecisionRoundPhase.SAFE_DECISION
        round_.boy_revealed_to_girl_at = now
        round_.decision_deadline_at = now + timedelta(hours=DECISION_GRACE_HOURS)
        round_.status_changed_at = now
        round_.save(
            update_fields=[
                "phase",
                "boy_revealed_to_girl_at",
                "decision_deadline_at",
                "status_changed_at",
            ]
        )
        boy = self._male_participant(chat)
        girl = self._female_participant(chat)
        cid = str(chat.id)
        if boy is not None:
            # Boy shown to girl only (exclude boy from the reveal event).
            transaction.on_commit(
                lambda: self._broadcast(
                    cid,
                    "safe.boy_revealed",
                    {"chat_id": cid},
                    exclude_user_id=str(boy.id),
                )
            )
        if girl is not None:
            transaction.on_commit(
                lambda: self._broadcast(
                    cid,
                    "safe.girl_reviewing",
                    {"chat_id": cid},
                    exclude_user_id=str(girl.id),
                )
            )
        transaction.on_commit(lambda: self._notify_safe_reviewing(chat))
        return ServiceResult.ok({"applied": True, "final_call": FinalCall.SAFE_REVEAL})

    # -- Safe reveal decision (girl) ----------------------------------------

    def submit_safe_decision(
        self, *, chat_id: str, user: User, choice: str
    ) -> ServiceResult[dict]:
        if choice not in (
            SafeRevealDecision.REVEAL_YOURSELF,
            SafeRevealDecision.EXIT,
        ):
            return ServiceResult.fail("VALIDATION_ERROR", "Invalid safe decision.")

        with transaction.atomic():
            from apps.chats.models import Chat

            chat = Chat.objects.select_for_update().get(id=chat_id)
            round_ = self._active_round_locked(chat)
            if round_ is None or round_.phase != DecisionRoundPhase.SAFE_DECISION:
                return ServiceResult.fail(
                    "CONFLICT", "No safe reveal decision is pending."
                )
            girl = self._female_participant(chat)
            if girl is None or girl.id != user.id:
                return ServiceResult.fail(
                    "FORBIDDEN", "Only the reviewing user can decide."
                )
            if round_.safe_decision != SafeRevealDecision.PENDING:
                return ServiceResult.fail("CONFLICT", "Decision already made.")

            round_.safe_decision = choice
            if choice == SafeRevealDecision.REVEAL_YOURSELF:
                round_.phase = DecisionRoundPhase.RESOLVED
                round_.status_changed_at = timezone.now()
                round_.save(
                    update_fields=["safe_decision", "phase", "status_changed_at"]
                )
                self._chats.mark_revealed(str(chat.id))
                transaction.on_commit(lambda: self._notify_revealed(chat.id))
                outcome = {"revealed": True}
            else:
                # EXIT after seeing the boy: payments consumed, NO coins (req 15).
                round_.phase = DecisionRoundPhase.CANCELLED
                round_.status_changed_at = timezone.now()
                round_.save(
                    update_fields=["safe_decision", "phase", "status_changed_at"]
                )
                self._chats.end_chat(str(chat.id), reason=EndReason.SAFE_REJECT)
                transaction.on_commit(
                    lambda: self._notify_ended(chat.id, reason="safe_reject")
                )
                outcome = {"ended": True, "reason": "safe_reject"}
        return ServiceResult.ok(outcome)

    # -- Exit / auto-exit ---------------------------------------------------

    def _resolve_exit(
        self, round_: DecisionRound, chat, *, exiting_user: User
    ) -> ServiceResult[dict]:
        """Unilateral exit (DECISION or PAYMENT phase). Any already-paid side is
        converted to coins (no cash refund); the chat ends."""
        self._credit_unmatched_payments(round_)
        round_.final_call = FinalCall.EXIT
        round_.phase = DecisionRoundPhase.CANCELLED
        round_.status_changed_at = timezone.now()
        round_.save(update_fields=["final_call", "phase", "status_changed_at"])
        self._chats.end_chat(str(chat.id), reason=EndReason.USER_EXIT)
        transaction.on_commit(lambda: self._notify_ended(chat.id, reason="exit"))
        return ServiceResult.ok({"ended": True, "reason": "exit"})

    def auto_exit_if_stale(self, chat) -> bool:
        """End a chat whose active round passed its deadline (24h grace or a
        stalled safe decision). Returns True if it ended the chat."""
        with transaction.atomic():
            from apps.chats.models import Chat

            chat = Chat.objects.select_for_update().get(id=chat.id)
            if chat.status in (ChatStatus.REVEALED, ChatStatus.ENDED):
                return False
            round_ = self._active_round_locked(chat)
            if round_ is None or round_.decision_deadline_at is None:
                return False
            if timezone.now() < round_.decision_deadline_at:
                return False
            # Past a safe-decision deadline the boy was already shown → consumed,
            # no coins. Otherwise convert any lone payment to coins.
            if round_.phase != DecisionRoundPhase.SAFE_DECISION:
                self._credit_unmatched_payments(round_)
            round_.phase = DecisionRoundPhase.CANCELLED
            round_.final_call = round_.final_call or FinalCall.EXIT
            round_.status_changed_at = timezone.now()
            round_.save(update_fields=["phase", "final_call", "status_changed_at"])
            self._chats.end_chat(str(chat.id), reason=EndReason.AUTO_EXIT)
        transaction.on_commit(lambda: self._notify_ended(chat.id, reason="auto_exit"))
        return True

    def _credit_unmatched_payments(self, round_: DecisionRound) -> None:
        """Credit coins for any side that paid but whose action won't execute."""
        for pd in round_.decisions.select_related("user").all():
            if pd.paid_at is None:
                continue
            coin_type = self._cancellation_coin_type(round_, pd.user)
            self._credits.credit(
                user=pd.user,
                coin_type=coin_type,
                amount=1,
                reason=CoinLedgerReason.CANCELLATION_CREDIT,
                idempotency_key=f"cancel:{round_.id}:{pd.user_id}",
                chat=round_.chat,
            )

    def _cancellation_coin_type(self, round_: DecisionRound, user: User) -> str:
        if round_.final_call == FinalCall.SAFE_REVEAL and user.gender == Gender.FEMALE:
            return CoinType.SAFE_REVEAL
        return CoinType.REVEAL

    # -- State read (reconnection) ------------------------------------------

    def get_decision_state(
        self, *, chat_id: str, user: User
    ) -> ServiceResult[dict]:
        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        if not self._chats.is_participant(chat, user):
            return ServiceResult.fail("FORBIDDEN", "You are not in this chat.")
        return ServiceResult.ok(self._state_payload(chat_id, user))

    def _state_payload(self, chat_id: str, user: User) -> dict:
        chat = self._chats.get_chat(chat_id)
        round_ = self._active_round(chat)
        mine = other = None
        if round_ is not None:
            for d in round_.decisions.all():
                if d.user_id == user.id:
                    mine = d
                else:
                    other = d
        girl = self._female_participant(chat)
        return {
            "chat_id": str(chat_id),
            "chat_status": chat.status,
            "eligible": self.is_eligible(chat),
            "available_choices": self.available_choices(chat, user),
            "phase": round_.phase if round_ else None,
            "final_call": (round_.final_call or None) if round_ else None,
            "my_choice": (mine.choice or None) if mine else None,
            "other_chosen": bool(other and other.choice),
            "my_paid": bool(mine and mine.paid_at),
            "other_paid": bool(other and other.paid_at),
            "deadline_at": (
                round_.decision_deadline_at.isoformat()
                if round_ and round_.decision_deadline_at
                else None
            ),
            "safe": {
                "boy_revealed": bool(round_ and round_.boy_revealed_to_girl_at),
                "decision": round_.safe_decision if round_ else None,
                "i_am_decider": bool(girl and girl.id == user.id),
            }
            if round_ and round_.phase == DecisionRoundPhase.SAFE_DECISION
            else None,
        }

    def safe_reveal_boy_visible_to(self, chat, viewer: User) -> bool:
        """Whether, in an active SAFE_DECISION, the boy is unmasked to ``viewer``
        (the reviewing girl). Used by the chat serializer for partial unmasking."""
        round_ = self._active_round(chat)
        if round_ is None or round_.phase != DecisionRoundPhase.SAFE_DECISION:
            return False
        if round_.boy_revealed_to_girl_at is None:
            return False
        girl = self._female_participant(chat)
        return girl is not None and girl.id == viewer.id

    # -- Participant helpers ------------------------------------------------

    def _female_participant(self, chat) -> User | None:
        for p in chat.participants.select_related("user").all():
            if p.user.gender == Gender.FEMALE:
                return p.user
        return None

    def _male_participant(self, chat) -> User | None:
        for p in chat.participants.select_related("user").all():
            if p.user.gender == Gender.MALE:
                return p.user
        return None

    def _participant_users(self, chat_id: str):
        from apps.chats.models import ChatParticipant

        return [
            p.user
            for p in ChatParticipant.objects.select_related("user").filter(
                chat_id=chat_id
            )
        ]

    # -- Notifications / WS -------------------------------------------------

    def _broadcast(self, chat_id, event, payload, *, exclude_user_id=None) -> None:
        broadcast_to_chat(
            str(chat_id), event, payload, exclude_user_id=exclude_user_id
        )

    def _notify_ready(self, chat, *, exclude_user_id) -> None:
        for user in self._participant_users(str(chat.id)):
            if user.id == exclude_user_id:
                continue
            self._notifications.create_notification(
                user=user,
                type="reveal.partner_ready",
                title="Your match is ready to reveal",
                body="Open the chat to choose what happens next.",
                action_type="OPEN_CHAT",
                action_payload={"chat_id": str(chat.id)},
            )

    def _notify_revealed(self, chat_id) -> None:
        self._broadcast(chat_id, "reveal.completed", {"chat_id": str(chat_id)})
        for user in self._participant_users(str(chat_id)):
            self._notifications.create_notification(
                user=user,
                type="reveal.completed",
                title="Identities revealed!",
                body="You can now see each other.",
                action_type="OPEN_CHAT",
                action_payload={"chat_id": str(chat_id)},
            )

    def _notify_extended(self, chat_id) -> None:
        self._broadcast(chat_id, "chat.extended", {"chat_id": str(chat_id)})
        for user in self._participant_users(str(chat_id)):
            self._notifications.create_notification(
                user=user,
                type="chat.extended",
                title="Your chat has been extended",
                body="You can keep chatting anonymously.",
                action_type="OPEN_CHAT",
                action_payload={"chat_id": str(chat_id)},
            )

    def _notify_safe_reviewing(self, chat) -> None:
        girl = self._female_participant(chat)
        if girl is not None:
            self._notifications.create_notification(
                user=girl,
                type="safe.boy_revealed",
                title="You can now see your match",
                body="Decide whether to reveal yourself.",
                action_type="OPEN_CHAT",
                action_payload={"chat_id": str(chat.id)},
            )

    def _notify_ended(self, chat_id, *, reason: str) -> None:
        self._broadcast(
            chat_id, "chat.ended", {"chat_id": str(chat_id), "reason": reason}
        )
        for user in self._participant_users(str(chat_id)):
            self._notifications.create_notification(
                user=user,
                type="chat.ended",
                title="This chat has ended",
                body="Share your feedback about the conversation.",
                action_type="OPEN_CHAT",
                action_payload={"chat_id": str(chat_id)},
            )
