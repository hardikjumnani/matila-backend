"""
Colleges domain models.

A ``College`` is the launch + membership unit: users belong to exactly one
college (resolved from their verified email domain), and the college's
``launch_date`` gates when its approved members can enter the core app
(matchmaking). See docs/COLLEGE_LAUNCH_PLAN.md.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.colleges.enums import LaunchMilestone
from apps.common.models import UUIDModel


class College(UUIDModel):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=150)
    # Lowercased email domains that map a sign-up to this college, e.g.
    # ["online.bits-pilani.ac.in"]. A user's domain must match an active college.
    allowed_email_domains = models.JSONField(default=list, blank=True)
    # When the college goes live. Null = unscheduled. Approved members may enter
    # matchmaking only once now >= launch_date.
    launch_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "colleges"
        ordering = ["name"]

    @property
    def is_launched(self) -> bool:
        return self.launch_date is not None and timezone.now() >= self.launch_date

    def __str__(self) -> str:
        return f"College<{self.code}>"


class LaunchNotification(UUIDModel):
    """Idempotency log for college-wide scheduled launch milestones — one row per
    (college, milestone) guarantees each countdown push fires exactly once."""

    college = models.ForeignKey(
        College,
        on_delete=models.CASCADE,
        related_name="launch_notifications",
    )
    milestone = models.CharField(max_length=20, choices=LaunchMilestone.choices)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "launch_notifications"
        constraints = [
            models.UniqueConstraint(
                fields=["college", "milestone"], name="uniq_launch_notification"
            ),
        ]

    def __str__(self) -> str:
        return f"LaunchNotification<{self.college_id} {self.milestone}>"
