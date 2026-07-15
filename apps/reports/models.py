"""
Reports domain models.

A report immediately freezes the associated chat (ReportService sets the chat
to ENDED with end_reason=REPORT) and preserves history for moderation. A user
may file at most one report per chat (enforced below).
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel

from .enums import ReportCategory, ReportStatus, ResolutionAction


class Report(UUIDModel):
    chat = models.ForeignKey(
        "chats.Chat",
        on_delete=models.PROTECT,
        related_name="reports",
    )
    reported_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="reports_made",
    )
    reported_user = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="reports_received",
    )

    category = models.CharField(max_length=25, choices=ReportCategory.choices)
    description = models.TextField(blank=True, default="")
    # Optional pointer to a specific offending message. SET_NULL keeps the
    # report intact if the message row is ever removed; this is a one-way
    # dependency (reports -> messaging) so it introduces no import cycle.
    reported_message = models.ForeignKey(
        "messaging.Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    status = models.CharField(
        max_length=15,
        choices=ReportStatus.choices,
        default=ReportStatus.OPEN,
    )
    admin_notes = models.TextField(blank=True, default="")
    resolution_action = models.CharField(
        max_length=20,
        choices=ResolutionAction.choices,
        default=ResolutionAction.NONE,
    )
    # Managed only through Admin APIs (never by the reporting user).
    is_false_report = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    status_changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "reports"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["chat", "reported_by"],
                name="uniq_report_per_chat_reporter",
            ),
        ]
        indexes = [
            # Moderation queue by status; reports against a given user.
            models.Index(fields=["status"], name="idx_report_status"),
            models.Index(fields=["reported_user"], name="idx_report_reported_user"),
        ]

    def __str__(self) -> str:
        return f"Report<{self.id}> chat={self.chat_id} {self.status}"
