"""Scheduled task: auto-exit chats whose decision round passed its deadline.

Covers the post-expiry 24h grace and stalled Safe Reveal decisions. Delegates to
RevealService.auto_exit_if_stale (converts lone payments to coins where due, ends
the chat, notifies). See docs/REVEAL_FLOW_SPEC.md.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.reveal.enums import TERMINAL_ROUND_PHASES
from apps.reveal.models import DecisionRound
from apps.reveal.services.reveal_service import RevealService

logger = logging.getLogger(__name__)


@shared_task(name="apps.reveal.tasks.auto_exit_stale_decisions")
def auto_exit_stale_decisions() -> int:
    now = timezone.now()
    due = (
        DecisionRound.objects.filter(decision_deadline_at__lte=now)
        .exclude(phase__in=TERMINAL_ROUND_PHASES)
        .select_related("chat")
    )
    service = RevealService()
    ended = 0
    for round_ in due:
        if service.auto_exit_if_stale(round_.chat):
            ended += 1
    if ended:
        logger.info("auto_exit_stale_decisions ended %d chat(s).", ended)
    return ended
