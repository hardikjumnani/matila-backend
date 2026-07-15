"""Serializers for the notifications API."""

from __future__ import annotations

from rest_framework import serializers

from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """User-facing notification (internal push status/metadata not exposed)."""

    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "body",
            "action_type",
            "action_payload",
            "priority",
            "is_read",
            "read_at",
            "expires_at",
            "created_at",
        ]
        read_only_fields = fields
