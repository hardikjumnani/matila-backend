"""Client-facing privacy API serializers."""

from __future__ import annotations

from rest_framework import serializers


class ViolationReportSerializer(serializers.Serializer):
    """A violation the frontend blocked client-side and is reporting for the log.

    All fields are client-supplied and untrusted. ``category`` is coerced to a
    known LeakCategory server-side (unknown -> a safe default); ``user`` is never
    taken from the client (always the authenticated caller).
    """

    attempted_text = serializers.CharField(max_length=4000, trim_whitespace=False)
    category = serializers.CharField(
        max_length=20, required=False, allow_blank=True, default=""
    )
    chat_id = serializers.UUIDField(required=False, allow_null=True)
    client_detectors = serializers.ListField(
        child=serializers.CharField(max_length=80),
        required=False,
        default=list,
        max_length=20,
    )
    # Accepted for completeness; the server's created_at is authoritative.
    occurred_at = serializers.DateTimeField(required=False)
