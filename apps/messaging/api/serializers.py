"""
Serializers for the messaging API.

Soft-deleted messages are masked (no content/media). Image media is served as a
short-lived signed URL only while it is AVAILABLE — once a view-once image is
viewed (or media expires/deletes), the URL is withheld, so consumed media is
never re-servable.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.common.api.serializers import ImageUploadSerializer
from apps.common.media import resolve_media_url
from apps.messaging.enums import MediaStatus, MediaVisibility, MessageType


class MessageSerializer(serializers.Serializer):
    """Read representation of a message."""

    id = serializers.UUIDField()
    chat_id = serializers.UUIDField()
    sender_id = serializers.UUIDField(allow_null=True)
    message_type = serializers.CharField()
    text_content = serializers.SerializerMethodField()
    media_url = serializers.SerializerMethodField()
    media_visibility = serializers.CharField()
    media_status = serializers.CharField(allow_blank=True)
    viewed_at = serializers.DateTimeField(allow_null=True)
    reply_to_message_id = serializers.UUIDField(allow_null=True)
    is_deleted = serializers.BooleanField()
    created_at = serializers.DateTimeField()

    def get_text_content(self, obj) -> str:
        return "" if obj.is_deleted else obj.text_content

    def get_media_url(self, obj) -> str | None:
        if obj.is_deleted or obj.message_type != MessageType.IMAGE:
            return None
        if obj.media_status != MediaStatus.AVAILABLE:
            return None
        return resolve_media_url(obj.media_url)


class SendTextMessageSerializer(serializers.Serializer):
    """Body for POST /chats/{id}/messages. Length is validated by the service
    so it can return the frozen MESSAGE_TOO_LONG code."""

    content = serializers.CharField(allow_blank=False, trim_whitespace=True)
    reply_to_message_id = serializers.UUIDField(required=False, allow_null=True)


class SendImageMessageSerializer(ImageUploadSerializer):
    """Body for POST /chats/{id}/messages/image."""

    media_visibility = serializers.ChoiceField(
        choices=MediaVisibility.choices,
        required=False,
        default=MediaVisibility.NORMAL,
    )
    reply_to_message_id = serializers.UUIDField(required=False, allow_null=True)
