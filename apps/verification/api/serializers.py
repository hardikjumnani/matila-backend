"""
Serializers for the verification API.

The user-facing representation deliberately excludes the uploaded document URLs:
verification documents are accessible only to admins (frozen security rule). The
client instead sees boolean upload-progress flags. The admin serializer (Step 9)
exposes the document URLs.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.verification.models import VerificationRequest


class VerificationRequestSerializer(serializers.ModelSerializer):
    """User-facing view of a verification attempt (no document URLs)."""

    college_id_uploaded = serializers.SerializerMethodField()
    gesture_selfie_uploaded = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequest
        fields = [
            "id",
            "attempt_number",
            "status",
            "gesture_type",
            "college_id_uploaded",
            "gesture_selfie_uploaded",
            "review_notes",
            "submitted_at",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_college_id_uploaded(self, obj: VerificationRequest) -> bool:
        return bool(obj.college_id_image_url)

    def get_gesture_selfie_uploaded(self, obj: VerificationRequest) -> bool:
        return bool(obj.gesture_selfie_image_url)
