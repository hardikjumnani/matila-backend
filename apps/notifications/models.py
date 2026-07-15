"""
Notifications domain models.

Stores in-app notification history and drives FCM push delivery (via a
background task). Deep linking is expressed through ``action_type`` and
``action_payload``. ``push_status`` tracks delivery internally and is not
exposed to regular users.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedUUIDModel, UUIDModel

from .enums import DevicePlatform, NotificationPriority, PushStatus


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


class DeviceToken(TimeStampedUUIDModel):
    """An FCM registration token for one of a user's devices.

    One user may have many device tokens (multiple devices). FCM tokens rotate,
    so registration upserts by ``device_id`` (a stable, mandatory, client-
    supplied device identifier): the same physical device keeps one row and
    simply updates its ``token``. Per-device logout deactivates a single row
    (``is_active = False``) rather than deleting it, preserving history. Push
    delivery (Step 8) targets active tokens only.

    NOTE: This table is an approved addition beyond the frozen schema — the
    frozen schema had no place to store FCM tokens.
    """

    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="device_tokens",
    )
    token = models.CharField(max_length=512, unique=True)
    # Stable, mandatory per-device identifier supplied by the client; the key
    # for rotation (update token in place) and per-device logout.
    device_id = models.CharField(max_length=255)
    platform = models.CharField(max_length=10, choices=DevicePlatform.choices)
    app_version = models.CharField(max_length=50, blank=True, default="")
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "device_tokens"
        ordering = ["-last_seen_at"]
        constraints = [
            # Exactly one row per (user, device_id): a rotating token updates the
            # existing device row instead of piling up duplicates.
            models.UniqueConstraint(
                fields=["user", "device_id"],
                name="uniq_device_per_user",
            ),
        ]
        indexes = [
            # Push delivery: active tokens for a user.
            models.Index(
                fields=["user", "is_active"], name="idx_devicetoken_user_active"
            ),
        ]

    def __str__(self) -> str:
        return f"DeviceToken<{self.id}> user={self.user_id} {self.platform}"
