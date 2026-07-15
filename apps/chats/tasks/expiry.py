"""Scheduled task: expire chats whose anonymous window has elapsed."""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService

logger = logging.getLogger(__name__)


@shared_task(name="apps.chats.tasks.expire_chats")
def expire_chats() -> int:
    """Expire ACTIVE/EXTENDED chats past their current-phase end time.

    Delegates each transition to ChatService (which notifies participants and
    broadcasts chat.state_updated). Returns the number of chats expired.
    """
    now = timezone.now()
    due_ids = list(
        Chat.objects.filter(
            status__in=[ChatStatus.ACTIVE, ChatStatus.EXTENDED],
            current_phase_ends_at__lte=now,
        ).values_list("id", flat=True)
    )
    service = ChatService()
    expired = 0
    for chat_id in due_ids:
        result = service.expire_chat(str(chat_id))
        if result.success and result.data.status == ChatStatus.EXPIRED:
            expired += 1
    if expired:
        logger.info("expire_chats expired %d chat(s).", expired)
    return expired
