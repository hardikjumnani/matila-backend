"""
Serializers for the users API.

Step 4 needs only read serialization of the authenticated user for the session
bootstrap response. Profile-update and onboarding request serializers are added
in Step 6. Serializers perform no business logic and no database access.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.users.models import User


class UserSerializer(serializers.ModelSerializer):
    """Read-only representation of a user's own profile."""

    class Meta:
        model = User
        fields = [
            "id",
            "college_email",
            "full_name",
            "profile_photo_url",
            "gender",
            "intent",
            "gender_preferences",
            "verification_status",
            "verified_at",
            "account_status",
            "onboarding_completed_at",
            "last_active_at",
            "created_at",
        ]
        read_only_fields = fields


class SessionResponseSerializer(serializers.Serializer):
    """Documents the session bootstrap response payload (for the OpenAPI schema)."""

    user = UserSerializer()
    next_action = serializers.ChoiceField(
        choices=[
            "COMPLETE_ONBOARDING",
            "SUBMIT_VERIFICATION",
            "WAIT_FOR_VERIFICATION",
            "GO_HOME",
        ]
    )
    created = serializers.BooleanField()
