"""
Notifications domain models.

Stores in-app notification history and drives FCM push delivery (via a
background task). Deep linking is expressed through ``action_type`` and
``action_payload``. ``push_status`` tracks delivery internally and is not
exposed to regular users.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import UUIDModel

from .enums import NotificationPriority, PushStatus


class Notification(UUIDModel):
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    # Free-form type key (e.g. "verification.approved"); not a fixed enum.
    type = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")

    # Deep-link target for the client.
    action_type = models.CharField(max_length=100, blank=True, default="")
    action_payload = models.JSONField(default=dict, blank=True)

    push_status = models.CharField(
        max_length=10,
        choices=PushStatus.choices,
        default=PushStatus.PENDING,
    )
    priority = models.CharField(
        max_length=10,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
    )
    metadata = models.JSONField(default=dict, blank=True)

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [
            # Notification list (per user, newest first) and unread-count query.
            models.Index(fields=["user", "-created_at"], name="idx_notif_user_created"),
            models.Index(fields=["user", "is_read"], name="idx_notif_user_read"),
        ]

    def __str__(self) -> str:
        return f"Notification<{self.id}> user={self.user_id} {self.type}"
