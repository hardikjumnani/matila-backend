"""Serializers for device-token registration."""

from __future__ import annotations

from rest_framework import serializers

from apps.notifications.enums import DevicePlatform
from apps.notifications.models import DeviceToken


class DeviceRegisterSerializer(serializers.Serializer):
    """Body for POST /users/me/devices."""

    token = serializers.CharField(max_length=512)
    device_id = serializers.CharField(max_length=255)
    platform = serializers.ChoiceField(choices=DevicePlatform.choices)
    app_version = serializers.CharField(
        max_length=50, required=False, allow_blank=True, default=""
    )


class DeviceTokenSerializer(serializers.ModelSerializer):
    """Response representation (the FCM token itself is not echoed back)."""

    class Meta:
        model = DeviceToken
        fields = [
            "id",
            "device_id",
            "platform",
            "app_version",
            "is_active",
            "last_seen_at",
        ]
        read_only_fields = fields
