"""
Serializers for the users API.

Serializers validate and shape data only — no business logic, no database
access. Editable-field rules (e.g. gender immutability after verification) are
enforced in AuthService, not here.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.common.media import resolve_media_url
from apps.users.enums import Gender, Intent
from apps.users.models import User

_ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


class UserSerializer(serializers.ModelSerializer):
    """Read-only representation of a user's own profile."""

    profile_photo_url = serializers.SerializerMethodField()
    college = serializers.SerializerMethodField()
    launched = serializers.SerializerMethodField()

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
            "college",
            "launched",
            "last_active_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_profile_photo_url(self, obj: User) -> str:
        return resolve_media_url(obj.profile_photo_url)

    def get_college(self, obj: User) -> dict | None:
        """College + launch state (name, launch_date, launched) — drives the FE
        countdown + routing."""
        from apps.colleges.services.college_service import CollegeService

        return CollegeService().launch_info(obj)["college"]

    def get_launched(self, obj: User) -> bool:
        from apps.colleges.services.college_service import CollegeService

        return CollegeService().is_user_launched(obj)


class UserProfileUpdateSerializer(serializers.Serializer):
    """Validates editable profile fields for PATCH /users/me."""

    full_name = serializers.CharField(max_length=150, required=False)
    gender = serializers.ChoiceField(choices=Gender.choices, required=False)
    intent = serializers.ChoiceField(choices=Intent.choices, required=False)
    gender_preferences = serializers.ListField(
        child=serializers.ChoiceField(choices=Gender.choices),
        required=False,
        allow_empty=True,
    )

    def validate(self, attrs: dict) -> dict:
        if not attrs:
            raise serializers.ValidationError("No editable fields were provided.")
        return attrs


class ProfilePhotoUploadSerializer(serializers.Serializer):
    """Validates a profile-photo upload.

    Uses FileField (not ImageField) to avoid a hard Pillow dependency; the
    content type is validated explicitly. Deep image inspection can be added
    with Pillow later if needed.
    """

    file = serializers.FileField()

    def validate_file(self, value):
        if value.content_type not in _ALLOWED_IMAGE_TYPES:
            raise serializers.ValidationError(
                "Unsupported image type. Use JPEG, PNG, or WebP."
            )
        return value


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
