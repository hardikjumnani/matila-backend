"""Serializers for the ratings API."""

from __future__ import annotations

from rest_framework import serializers

from apps.ratings.models import Rating


class RatingSerializer(serializers.ModelSerializer):
    chat_id = serializers.UUIDField(read_only=True)
    rated_user_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Rating
        fields = [
            "id",
            "chat_id",
            "rated_user_id",
            "questionnaire_version",
            "responses",
            "feedback_text",
            "created_at",
        ]
        read_only_fields = fields


class SubmitRatingRequestSerializer(serializers.Serializer):
    questionnaire_version = serializers.CharField()
    # Value validation (allowed response codes, known question keys) is performed
    # in RatingService against the active questionnaire.
    responses = serializers.DictField(child=serializers.CharField())
    feedback_text = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500
    )
