"""
Device token service.

Owns ``device_tokens``. Handles device registration with token rotation (upsert
keyed on the user's device_id), per-device logout (deactivation, not deletion),
and resolving a user's active tokens for push delivery. Also deactivates tokens
that FCM reports as invalid/unregistered.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.common.results import ServiceResult
from apps.notifications.enums import DevicePlatform
from apps.notifications.models import DeviceToken
from apps.users.models import User

logger = logging.getLogger(__name__)


class DeviceTokenService:
    """Register, rotate, and deactivate a user's push device tokens."""

    def register(
        self,
        *,
        user: User,
        token: str,
        device_id: str,
        platform: DevicePlatform | str,
        app_version: str = "",
    ) -> ServiceResult[DeviceToken]:
        """Register or update the token for a user's device (idempotent upsert).

        Rotation: the same ``(user, device_id)`` keeps one row and updates its
        token. The token is globally unique, so it is first detached from any
        other device row it might currently occupy (e.g. after a reinstall or
        device hand-off).
        """
        if not token or not device_id:
            return ServiceResult.fail(
                "VALIDATION_ERROR", "token and device_id are required."
            )
        with transaction.atomic():
            DeviceToken.objects.filter(token=token).exclude(
                user=user, device_id=device_id
            ).delete()
            device, _created = DeviceToken.objects.update_or_create(
                user=user,
                device_id=device_id,
                defaults={
                    "token": token,
                    "platform": platform,
                    "app_version": app_version,
                    "is_active": True,
                    "last_seen_at": timezone.now(),
                },
            )
        return ServiceResult.ok(device)

    def deactivate_device(self, *, user: User, device_id: str) -> ServiceResult[None]:
        """Per-device logout: deactivate the user's token for a device."""
        updated = DeviceToken.objects.filter(
            user=user, device_id=device_id, is_active=True
        ).update(is_active=False)
        if not updated:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Device not found.")
        return ServiceResult.ok(None)

    def deactivate_tokens(self, tokens: list[str]) -> int:
        """Deactivate specific tokens (used when FCM reports them invalid)."""
        if not tokens:
            return 0
        return DeviceToken.objects.filter(token__in=tokens, is_active=True).update(
            is_active=False
        )

    def active_tokens_for(self, user: User) -> QuerySet[DeviceToken]:
        return DeviceToken.objects.filter(user=user, is_active=True)
