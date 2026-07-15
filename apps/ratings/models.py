"""
Ratings domain models.

Post-chat feedback for internal analytics only; never shown publicly. The
questionnaire is backend-driven and versioned, so answers are stored as a JSON
payload validated by RatingService against the active questionnaire version.
Each user may rate a given chat at most once.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import UUIDModel


class Rating(UUIDModel):
    chat = models.ForeignKey(
        "chats.Chat",
        on_delete=models.PROTECT,
        related_name="ratings",
    )
    rated_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="ratings_given",
    )
    rated_user = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="ratings_received",
    )

    questionnaire_version = models.CharField(max_length=50)
    # Map of question-key -> RatingResponse value; validated in the service.
    responses = models.JSONField(default=dict)
    # Optional free text, capped at 500 characters per the frozen rules.
    feedback_text = models.CharField(max_length=500, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ratings"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["chat", "rated_by"],
                name="uniq_rating_per_chat_rater",
            ),
        ]
        indexes = [
            models.Index(fields=["chat"], name="idx_rating_chat"),
        ]

    def __str__(self) -> str:
        return f"Rating<{self.id}> chat={self.chat_id} by={self.rated_by_id}"
