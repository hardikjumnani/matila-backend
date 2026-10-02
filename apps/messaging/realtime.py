"""
Message event payload builder for realtime broadcasts.

Lives in the domain layer (not the API layer) so services can build event
payloads without importing DRF serializers. Mirrors the fields of
``MessageSerializer`` and applies the same masking rules (deleted content
hidden; media URL served only while AVAILABLE).
"""

from __future__ import annotations

from typing import Any

from apps.common.media import resolve_media_url
from apps.messaging.enums import MediaStatus, MediaVisibility, MessageType
from apps.messaging.models import Message


def build_message_payload(message: Message) -> dict[str, Any]:
    # VIEW_ONCE media never ships a URL — the recipient fetches the bytes once via
    # POST /messages/{id}/view (server-mediated, exactly-once). ``media_pending``
    # tells the client to render the "tap to view" bubble. See
    # docs/REVEAL_FLOW_SPEC.md / view-once hardening.
    media_url = None
    media_pending = False
    if (
        not message.is_deleted
        and message.message_type == MessageType.IMAGE
        and message.media_status == MediaStatus.AVAILABLE
    ):
        if message.media_visibility == MediaVisibility.VIEW_ONCE:
            media_pending = True
        else:
            media_url = resolve_media_url(message.media_url)
    return {
        "id": str(message.id),
        "chat_id": str(message.chat_id),
        "sender_id": str(message.sender_id) if message.sender_id else None,
        "message_type": message.message_type,
        "text_content": "" if message.is_deleted else message.text_content,
        "media_url": media_url,
        "media_pending": media_pending,
        "media_visibility": message.media_visibility,
        "media_status": message.media_status,
        "reply_to_message_id": (
            str(message.reply_to_message_id) if message.reply_to_message_id else None
        ),
        "is_deleted": message.is_deleted,
        "created_at": message.created_at.isoformat(),
    }
