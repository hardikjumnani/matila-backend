"""Veil persistence models.

``LeakEvent`` is the audit/review record for every flagged message; ``LeakStrike``
is the per-user repeat counter that drives escalation.

NOTE (temporary policy — see docs/VEIL_ENGINE_PLAN.md principle #7): for now we
deliberately store the **raw** offending message so admins can assess and judge.
Redaction/hashing is a later revisit.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import TimeStampedUUIDModel, UUIDModel

from .enums import (
    LeakAction,
    LeakCategory,
    LeakSeverity,
    MuffleMode,
    ProfanityTier,
    VeilMode,
)


class LeakEvent(UUIDModel):
    chat = models.ForeignKey(
        "chats.Chat",
        on_delete=models.CASCADE,
        related_name="leak_events",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="leak_events",
    )

    category = models.CharField(max_length=15, choices=LeakCategory.choices)
    severity = models.CharField(max_length=6, choices=LeakSeverity.choices)
    action = models.CharField(max_length=10, choices=LeakAction.choices)
    mode = models.CharField(max_length=10, choices=VeilMode.choices)
    rule_version = models.CharField(max_length=40, default="")

    detectors = models.JSONField(default=list, blank=True)
    # Temporary: full raw message + representative matched span, for admin review.
    raw_message = models.TextField(blank=True, default="")
    matched_span = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "leak_events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"], name="idx_leak_user_created"),
            models.Index(fields=["chat", "created_at"], name="idx_leak_chat_created"),
            models.Index(fields=["category"], name="idx_leak_category"),
        ]

    def __str__(self) -> str:
        return f"LeakEvent<{self.id}> user={self.user_id} {self.category}/{self.action}"


class ProfanityEvent(UUIDModel):
    """Audit/review record for a masked (T1) or flagged (T2) message. Stores the
    raw original + masked output for admin review (temporary raw-logging policy,
    same as LeakEvent)."""

    chat = models.ForeignKey(
        "chats.Chat",
        on_delete=models.CASCADE,
        related_name="profanity_events",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="profanity_events",
    )

    tier = models.CharField(max_length=10, choices=ProfanityTier.choices)
    mode = models.CharField(max_length=10, choices=MuffleMode.choices)
    rule_version = models.CharField(max_length=40, default="")

    words = models.JSONField(default=list, blank=True)
    raw_message = models.TextField(blank=True, default="")
    masked_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "profanity_events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"], name="idx_prof_user_created"),
            models.Index(fields=["chat", "created_at"], name="idx_prof_chat_created"),
            models.Index(fields=["tier"], name="idx_prof_tier"),
        ]

    def __str__(self) -> str:
        return f"ProfanityEvent<{self.id}> user={self.user_id} {self.tier}"


class LeakStrike(TimeStampedUUIDModel):
    user = models.OneToOneField(
        "users.User",
        on_delete=models.CASCADE,
        related_name="leak_strike",
    )
    count = models.PositiveIntegerField(default=0)
    last_event_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "leak_strikes"

    def __str__(self) -> str:
        return f"LeakStrike<{self.id}> user={self.user_id} count={self.count}"
