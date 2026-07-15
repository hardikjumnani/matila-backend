"""
Verification domain models.

Every verification attempt is an immutable, append-only record: a resubmission
creates a NEW row with an incremented ``attempt_number`` rather than mutating a
prior attempt. This preserves the full audit trail of a user's verification
history, as required by the frozen schema.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import TimeStampedUUIDModel
from apps.users.enums import VerificationStatus


class VerificationRequest(TimeStampedUUIDModel):
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="verification_requests",
    )
    # 1-based counter of this user's attempts; unique per user (see Meta).
    attempt_number = models.PositiveIntegerField()

    # Uploaded document URLs (S3). Populated by the upload endpoints before the
    # request is submitted for review.
    college_id_image_url = models.URLField(max_length=512, blank=True, default="")
    gesture_selfie_image_url = models.URLField(max_length=512, blank=True, default="")
    # The gesture the user was instructed to perform, drawn from the configured
    # gesture pool (app_config.gesture_pool); free-form, not a fixed enum.
    gesture_type = models.CharField(max_length=100, blank=True, default="")

    status = models.CharField(
        max_length=25,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    review_notes = models.TextField(blank=True, default="")
    # The admin (a users.User whose email is on ADMIN_EMAILS) who reviewed this
    # request, if any.
    reviewed_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "verification_requests"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "attempt_number"],
                name="uniq_verification_attempt_per_user",
            ),
        ]
        indexes = [
            # Admin review queue: pending requests, oldest first.
            models.Index(fields=["status"], name="idx_verif_status"),
            models.Index(
                fields=["user", "-attempt_number"], name="idx_verif_user_attempt"
            ),
        ]

    def __str__(self) -> str:
        return (
            f"VerificationRequest<{self.id}> user={self.user_id} #{self.attempt_number}"
        )
