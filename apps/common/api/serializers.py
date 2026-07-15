"""
Shared serializers reused across API modules.
"""

from __future__ import annotations

from rest_framework import serializers

# Accepted image MIME types for uploads. Deep image validation (via Pillow) is
# intentionally omitted; the content type is validated here and the object is
# streamed to private storage.
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


class ImageUploadSerializer(serializers.Serializer):
    """Validates a single uploaded image by MIME type."""

    file = serializers.FileField()

    def validate_file(self, value):
        if getattr(value, "content_type", None) not in ALLOWED_IMAGE_TYPES:
            raise serializers.ValidationError(
                "Unsupported image type. Use JPEG, PNG, or WebP."
            )
        return value
