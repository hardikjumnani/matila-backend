"""
Admin serializers.

Unlike the user-facing serializers, these expose moderation-relevant detail:
verification document URLs (admins may review them), report admin notes, and
raw message content as chat evidence.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.common.media import resolve_media_url
from apps.messaging.enums import MediaStatus
from apps.messaging.models import Message
from apps.reports.enums import ResolutionAction
from apps.reports.models import Report
from apps.verification.models import VerificationRequest


class AdminVerificationRequestSerializer(serializers.ModelSerializer):
    """Verification request with signed document URLs for review."""

    user_id = serializers.UUIDField(read_only=True)
    reviewed_by_id = serializers.UUIDField(read_only=True, allow_null=True)
    college_id_image_url = serializers.SerializerMethodField()
    gesture_selfie_image_url = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequest
        fields = [
            "id",
            "user_id",
            "attempt_number",
            "status",
            "gesture_type",
            "college_id_image_url",
            "gesture_selfie_image_url",
            "review_notes",
            "reviewed_by_id",
            "submitted_at",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_college_id_image_url(self, obj: VerificationRequest) -> str:
        return resolve_media_url(obj.college_id_image_url)

    def get_gesture_selfie_image_url(self, obj: VerificationRequest) -> str:
        return resolve_media_url(obj.gesture_selfie_image_url)


class ReviewActionSerializer(serializers.Serializer):
    """Optional reviewer notes for approve/reject/resubmission."""

    notes = serializers.CharField(required=False, allow_blank=True, default="")


class AdminReportSerializer(serializers.ModelSerializer):
    """Full report view including moderation fields."""

    chat_id = serializers.UUIDField(read_only=True)
    reported_by_id = serializers.UUIDField(read_only=True)
    reported_user_id = serializers.UUIDField(read_only=True)
    reported_message_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Report
        fields = [
            "id",
            "chat_id",
            "reported_by_id",
            "reported_user_id",
            "category",
            "description",
            "reported_message_id",
            "status",
            "admin_notes",
            "resolution_action",
            "is_false_report",
            "created_at",
            "reviewed_at",
        ]
        read_only_fields = fields


class AdminMessageSerializer(serializers.Serializer):
    """Chat evidence for moderation (raw content, including deleted)."""

    id = serializers.UUIDField()
    sender_id = serializers.UUIDField(allow_null=True)
    message_type = serializers.CharField()
    text_content = serializers.CharField()
    media_url = serializers.SerializerMethodField()
    is_deleted = serializers.BooleanField()
    created_at = serializers.DateTimeField()

    def get_media_url(self, obj: Message) -> str | None:
        if obj.media_url and obj.media_status != MediaStatus.DELETED:
            return resolve_media_url(obj.media_url)
        return None


class ResolveReportSerializer(serializers.Serializer):
    resolution_action = serializers.ChoiceField(choices=ResolutionAction.choices)
    admin_notes = serializers.CharField(required=False, allow_blank=True, default="")
    is_false_report = serializers.BooleanField(required=False, default=False)


class DismissReportSerializer(serializers.Serializer):
    is_false_report = serializers.BooleanField(required=False, default=False)
    admin_notes = serializers.CharField(required=False, allow_blank=True, default="")
