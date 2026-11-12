"""Scheduled task: pre-expiry "ending soon" reminders for anonymous chats.

Pushes a one-time reminder to both people in a live anonymous chat as it nears
expiry, at each configured threshold (default 1 hour and 30 minutes before).
Each threshold fires at most once per expiry window; an extension moves the
deadline and re-arms the reminders (the sent thresholds are stamped against the
exact deadline they were sent for).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.chats.aliases import anonymous_alias
from apps.chats.enums import ChatPhase, ChatStatus, ParticipantStatus
from apps.chats.models import Chat, ChatParticipant
from apps.common.realtime import chat_presence_key
from apps.configuration.constants import AppConfigKey, FeatureFlagKey
from apps.configuration.services.configuration_service import ConfigurationService
from apps.notifications.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


@shared_task(name="apps.chats.tasks.send_expiry_reminders")
def send_expiry_reminders() -> int:
    """Send due pre-expiry reminders. Returns the number of chats reminded."""
    config = ConfigurationService()
    if not config.is_feature_enabled(FeatureFlagKey.CHAT_EXPIRY_REMINDER_ENABLED):
        return 0
    thresholds = _resolve_thresholds(config)
    if not thresholds:
        return 0

    now = timezone.now()
    horizon = now + timedelta(minutes=max(thresholds))
    # Only anonymous, still-live chats whose deadline is within the widest
    # threshold. Small set, so the per-threshold decision is done in Python.
    due_ids = list(
        Chat.objects.filter(
            status__in=[ChatStatus.ACTIVE, ChatStatus.EXTENDED],
            current_phase=ChatPhase.ANONYMOUS,
            current_phase_ends_at__gt=now,
            current_phase_ends_at__lte=horizon,
        ).values_list("id", flat=True)
    )

    reminded = 0
    for chat_id in due_ids:
        try:
            if _process_chat(str(chat_id), thresholds):
                reminded += 1
        except Exception:  # noqa: BLE001 — one bad chat must not stop the sweep.
            logger.exception("send_expiry_reminders failed for chat %s", chat_id)
    if reminded:
        logger.info("send_expiry_reminders reminded %d chat(s).", reminded)
    return reminded


def _resolve_thresholds(config: ConfigurationService) -> list[int]:
    """Positive minute thresholds, de-duplicated and sorted most-distant first."""
    raw = config.get_config(AppConfigKey.CHAT_EXPIRY_REMINDER_MINUTES) or []
    out: set[int] = set()
    for value in raw:
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            continue
        if minutes > 0:
            out.add(minutes)
    return sorted(out, reverse=True)


def _process_chat(chat_id: str, thresholds: list[int]) -> bool:
    """Send the most-urgent due reminder for one chat (row-locked). Idempotent."""
    with transaction.atomic():
        chat = Chat.objects.select_for_update().filter(id=chat_id).first()
        if chat is None:
            return False
        # Re-check under the lock: state may have moved since the candidate scan.
        if (
            chat.status not in (ChatStatus.ACTIVE, ChatStatus.EXTENDED)
            or chat.current_phase != ChatPhase.ANONYMOUS
            or chat.current_phase_ends_at is None
        ):
            return False

        now = timezone.now()
        ends_at = chat.current_phase_ends_at
        remaining_min = (ends_at - now).total_seconds() / 60.0
        if remaining_min <= 0:
            return False  # about to be expired by the expiry task; no reminder.

        stamp = ends_at.isoformat()
        state = chat.expiry_reminder_state or {}
        if state.get("for") != stamp:
            # New or extended window: re-arm every threshold.
            state = {"for": stamp, "sent": []}
        sent = {int(x) for x in state.get("sent", [])}

        # Thresholds already crossed but not yet sent (thresholds is descending).
        due = [t for t in thresholds if remaining_min <= t and t not in sent]
        if not due:
            return False

        # Send one push for the most urgent crossed threshold, and mark ALL the
        # crossed-but-unsent thresholds so a lagged sweep neither double-buzzes
        # nor fires a stale, less-urgent reminder later.
        chosen = min(due)
        _send_reminder(chat, minutes=chosen, ends_at=ends_at)
        sent.update(due)
        state["sent"] = sorted(sent)
        chat.expiry_reminder_state = state
        chat.save(update_fields=["expiry_reminder_state"])
        return True


def _send_reminder(chat: Chat, *, minutes: int, ends_at) -> None:
    """Notify each active participant (push + inbox), identity-safe.

    Skips a participant currently reading this chat (they see the in-app
    countdown). The title is the partner's per-chat alias, never a real name.
    """
    notifications = NotificationService()
    body = _body_for(minutes)
    participants = list(
        ChatParticipant.objects.select_related("user").filter(
            chat=chat, status=ParticipantStatus.ACTIVE
        )
    )
    all_ids = [p.user_id for p in participants]
    for participant in participants:
        if cache.get(chat_presence_key(str(chat.id), str(participant.user_id))):
            continue  # actively in the chat; the countdown is already visible.
        other_id = next((uid for uid in all_ids if uid != participant.user_id), None)
        alias = (
            anonymous_alias(str(chat.id), str(other_id))
            if other_id is not None
            else "Your chat"
        )
        notifications.create_notification(
            user=participant.user,
            type="chat.expiring",
            title=alias,
            body=body,
            action_type="OPEN_CHAT",
            action_payload={"chat_id": str(chat.id)},
            metadata={"minutes": minutes, "chat_id": str(chat.id)},
            expires_at=ends_at,
        )


def _body_for(minutes: int) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60
        when = f"about {hours} hour" + ("" if hours == 1 else "s")
    else:
        when = f"about {minutes} minutes"
    return f"This chat ends in {when}. Reveal or keep chatting before it expires."
