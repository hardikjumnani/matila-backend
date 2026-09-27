"""
Reveal / decision domain models.

A ``DecisionRound`` is one negotiation attempt on a chat: both participants pick
a choice, the service computes a deterministic ``final_call``, then a payment
phase executes it. SAFE_REVEAL adds a post-payment ``SAFE_DECISION`` sub-phase.
Only one non-terminal round exists per chat at a time. See
docs/REVEAL_FLOW_SPEC.md.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel

from .enums import (
    DecisionChoice,
    DecisionRoundPhase,
    FinalCall,
    RevealTrigger,
    SafeRevealDecision,
)


class DecisionRound(UUIDModel):
    chat = models.ForeignKey(
        "chats.Chat",
        on_delete=models.CASCADE,
        related_name="decision_rounds",
    )
    trigger = models.CharField(max_length=10, choices=RevealTrigger.choices)
    phase = models.CharField(
        max_length=15,
        choices=DecisionRoundPhase.choices,
        default=DecisionRoundPhase.DECISION,
    )
    final_call = models.CharField(
        max_length=12, choices=FinalCall.choices, blank=True, default=""
    )
    # Deadline by which this round must complete before auto-exit (expiry rounds
    # and the safe-decision sub-phase set this to now + 24h).
    decision_deadline_at = models.DateTimeField(null=True, blank=True)

    # Safe-reveal sub-phase state.
    boy_revealed_to_girl_at = models.DateTimeField(null=True, blank=True)
    safe_decision = models.CharField(
        max_length=15,
        choices=SafeRevealDecision.choices,
        default=SafeRevealDecision.PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    status_changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "decision_rounds"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["chat", "phase"], name="idx_round_chat_phase"),
        ]

    def __str__(self) -> str:
        return (
            f"DecisionRound<{self.id}> chat={self.chat_id} "
            f"{self.phase}/{self.final_call or '-'}"
        )


class ParticipantDecision(UUIDModel):
    round = models.ForeignKey(
        DecisionRound,
        on_delete=models.CASCADE,
        related_name="decisions",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="participant_decisions",
    )
    choice = models.CharField(
        max_length=12, choices=DecisionChoice.choices, blank=True, default=""
    )
    chosen_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_with_coin = models.BooleanField(default=False)

    class Meta:
        db_table = "participant_decisions"
        constraints = [
            models.UniqueConstraint(
                fields=["round", "user"],
                name="uniq_decision_per_round_user",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"ParticipantDecision<{self.id}> round={self.round_id} "
            f"user={self.user_id} {self.choice or '-'}"
        )
