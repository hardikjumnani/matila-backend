"""
Reveal domain models.

Each participant records an independent reveal intent — there is no
accept/decline workflow, and neither user is told who initiated first. Mutual
intent plus successful payment by both users completes the reveal (handled by
RevealService / PaymentService).
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel

from .enums import RevealIntentStatus, RevealTriggerType


class RevealIntent(UUIDModel):
    chat = models.ForeignKey(
        "chats.Chat",
        on_delete=models.CASCADE,
        related_name="reveal_intents",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="reveal_intents",
    )
    status = models.CharField(
        max_length=10,
        choices=RevealIntentStatus.choices,
        default=RevealIntentStatus.PENDING,
    )
    trigger_type = models.CharField(
        max_length=12,
        choices=RevealTriggerType.choices,
        default=RevealTriggerType.MANUAL,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    status_changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "reveal_intents"
        constraints = [
            models.UniqueConstraint(
                fields=["chat", "user"],
                name="uniq_reveal_intent_per_chat_user",
            ),
        ]
        indexes = [
            models.Index(fields=["chat"], name="idx_reveal_chat"),
        ]

    def __str__(self) -> str:
        return f"RevealIntent<{self.id}> chat={self.chat_id} user={self.user_id} {self.status}"
