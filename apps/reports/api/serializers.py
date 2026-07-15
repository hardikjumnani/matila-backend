"""Serializers for the reports API."""

from __future__ import annotations

from rest_framework import serializers

from apps.reports.enums import ReportCategory
from apps.reports.models import Report


class ReportSerializer(serializers.ModelSerializer):
    """Reporter-facing view of a report (admin notes are not exposed)."""

    chat_id = serializers.UUIDField(read_only=True)
    reported_user_id = serializers.UUIDField(read_only=True)
    reported_message_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Report
        fields = [
            "id",
            "chat_id",
            "reported_user_id",
            "category",
            "description",
            "reported_message_id",
            "status",
            "resolution_action",
            "is_false_report",
            "created_at",
            "reviewed_at",
        ]
        read_only_fields = fields


class CreateReportRequestSerializer(serializers.Serializer):
    chat_id = serializers.UUIDField()
    category = serializers.ChoiceField(choices=ReportCategory.choices)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    reported_message_id = serializers.UUIDField(required=False, allow_null=True)
