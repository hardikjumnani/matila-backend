"""
Media URL resolution.

Stored media fields hold Azure Blob object keys, not URLs. When Blob storage is
configured, keys are resolved to short-lived SAS URLs for the response; in local
development (no Blob storage) the raw key is returned so serializers work
without Azure.
"""

from __future__ import annotations

from django.conf import settings


def resolve_media_url(key: str) -> str:
    """Return an access URL for a stored media key ("" when unset)."""
    if not key:
        return ""
    if not getattr(settings, "USE_AZURE_BLOB", False):
        return key
    # Imported lazily so this module has no hard dependency on the Azure SDK.
    from apps.common.services.storage_service import StorageService

    return StorageService().generate_presigned_url(key)
