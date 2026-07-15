"""
Realtime delivery helper (channel-layer broadcast).

A thin, infrastructure-level abstraction over the Channels channel layer, used
to push events to a chat's WebSocket group. It is a delivery concern — like
notifications — not business logic; services call it (from synchronous code,
typically inside ``transaction.on_commit``) and the consumer forwards the event
to connected sockets.

Synchronous callers use :func:`broadcast_to_chat` (wraps ``group_send`` with
``async_to_sync``). The async consumer must instead ``await
channel_layer.group_send`` directly — never call this from the event loop.
"""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)

# Channel-layer message type -> consumer handler ``chat_broadcast``.
GROUP_MESSAGE_TYPE = "chat.broadcast"


def chat_group_name(chat_id: str) -> str:
    return f"chat_{chat_id}"


def build_group_message(
    event: str, payload: dict[str, Any], *, exclude_user_id: str | None = None
) -> dict[str, Any]:
    """Construct the channel-layer message envelope for a chat broadcast."""
    return {
        "type": GROUP_MESSAGE_TYPE,
        "event": event,
        "payload": payload,
        "exclude_user_id": str(exclude_user_id) if exclude_user_id else None,
        "timestamp": timezone.now().isoformat(),
    }


def broadcast_to_chat(
    chat_id: str,
    event: str,
    payload: dict[str, Any],
    *,
    exclude_user_id: str | None = None,
) -> None:
    """Broadcast an event to a chat group from synchronous code.

    Safe to call when no channel layer is configured (no-op) and never raises
    into the caller — delivery failures must not roll back committed business
    state.
    """
    layer = get_channel_layer()
    if layer is None:
        return
    message = build_group_message(event, payload, exclude_user_id=exclude_user_id)
    try:
        async_to_sync(layer.group_send)(chat_group_name(chat_id), message)
    except Exception as exc:  # noqa: BLE001 — delivery is best-effort.
        logger.warning("Realtime broadcast failed for chat %s: %s", chat_id, exc)
