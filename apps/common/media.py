"""
Media URL resolution.

Stored media fields hold S3 object keys, not URLs. When S3 is configured, keys
are resolved to short-lived presigned URLs for the response; in local
development (no S3) the raw key is returned so serializers work without AWS.
"""

from __future__ import annotations

from django.conf import settings


def resolve_media_url(key: str) -> str:
    """Return an access URL for a stored media key ("" when unset)."""
    if not key:
        return ""
    if not getattr(settings, "USE_S3", False):
        return key
    # Imported lazily so this module has no hard dependency on boto3 at import.
    from apps.common.services.storage_service import StorageService

    return StorageService().generate_presigned_url(key)
