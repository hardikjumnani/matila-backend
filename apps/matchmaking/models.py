"""
Matchmaking domain models.

``MatchQueue`` is an ephemeral queue: rows are removed after a successful match,
cancellation, or timeout (per the frozen schema). ``intent`` and
``gender_preferences`` are denormalized from the user at join time so the
matcher can filter compatible buckets without a join back to ``users``.
"""

from __future__ import annotations

import uuid

from django.db import models

from apps.common.models import UUIDModel
from apps.users.enums import Intent

from .enums import MatchQueueStatus


class MatchQueue(UUIDModel):
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="match_queue_entries",
    )
    intent = models.CharField(max_length=20, choices=Intent.choices)
    # Denormalized copy of the user's gender_preferences (JSON list of genders).
    gender_preferences = models.JSONField(default=list, blank=True)
    # Correlates a single client-side search attempt.
    matchmaking_session_id = models.UUIDField(default=uuid.uuid4, db_index=True)

    status = models.CharField(
        max_length=10,
        choices=MatchQueueStatus.choices,
        default=MatchQueueStatus.SEARCHING,
    )
    joined_queue_at = models.DateTimeField(auto_now_add=True)
    matched_at = models.DateTimeField(null=True, blank=True)

    is_online = models.BooleanField(default=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "match_queue"
        constraints = [
            # A user may hold only one active (SEARCHING) queue entry at a time.
            # Enforced at the database level via a partial unique index.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status=MatchQueueStatus.SEARCHING),
                name="uniq_active_queue_entry_per_user",
            ),
        ]
        indexes = [
            # Matcher scans the active bucket by intent, oldest first.
            models.Index(
                fields=["status", "intent", "joined_queue_at"],
                name="idx_queue_status_intent",
            ),
            # Stale-entry cleanup scans by heartbeat.
            models.Index(
                fields=["status", "last_heartbeat_at"],
                name="idx_queue_status_heartbeat",
            ),
        ]

    def __str__(self) -> str:
        return f"MatchQueue<{self.id}> user={self.user_id} {self.status}"
