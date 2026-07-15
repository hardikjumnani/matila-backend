"""
Chat WebSocket consumer.

Implements the frozen WEBSOCKET_PROTOCOL_DESIGN. The consumer stays thin: it
authenticates the connection, enforces participation and chat-state rules, and
routes events. Message persistence goes through MessageService (the single
source of truth), and all persistent-event broadcasts (message.new, chat.read,
etc.) are emitted by the services via transaction.on_commit — so this consumer
only sends the sender-only ack and the ephemeral typing/presence events, and
forwards group broadcasts to the socket.

Ephemeral typing/presence state lives in Redis with short TTLs and is never
persisted.
"""

from __future__ import annotations

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.utils import timezone

from apps.chats.models import Chat, ChatParticipant
from apps.chats.services.chat_service import ChatService
from apps.common.realtime import chat_group_name
from apps.messaging.services.message_service import MessageService

logger = logging.getLogger(__name__)

PRESENCE_TTL_SECONDS = 60
TYPING_TTL_SECONDS = 5

# Rejection codes (WEBSOCKET_PROTOCOL_DESIGN).
_CODE_AUTH_FAILED = 4001
_CODE_NOT_PARTICIPANT = 4002
_CODE_INVALID_CHAT = 4004


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """Real-time chat connection for a single chat room."""

    # -- Lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        self.user = self.scope.get("user")
        self.chat_id = str(self.scope["url_route"]["kwargs"]["chat_id"])

        if not self._is_authenticated(self.user):
            await self.close(code=_CODE_AUTH_FAILED)
            return
        if not await self._chat_exists(self.chat_id):
            await self.close(code=_CODE_INVALID_CHAT)
            return
        if not await self._is_participant(self.chat_id, self.user.id):
            await self.close(code=_CODE_NOT_PARTICIPANT)
            return

        self.group_name = chat_group_name(self.chat_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self._set_presence(online=True)

    async def disconnect(self, code: int) -> None:
        if getattr(self, "group_name", None):
            await self._set_presence(online=False)
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # -- Inbound event routing ---------------------------------------------

    async def receive_json(self, content: dict, **kwargs) -> None:
        event = content.get("event")
        payload = content.get("payload") or {}
        handlers = {
            "message.send": self._on_message_send,
            "chat.read": self._on_chat_read,
            "message.viewed": self._on_message_viewed,
            "typing.start": self._on_typing_start,
            "typing.stop": self._on_typing_stop,
            "presence.heartbeat": self._on_presence_heartbeat,
        }
        handler = handlers.get(event)
        if handler is None:
            await self._send_error("INVALID_PAYLOAD", f"Unknown event: {event}.")
            return
        try:
            await handler(payload)
        except Exception:  # noqa: BLE001 — never let one event kill the socket.
            logger.exception("Error handling WebSocket event %s", event)
            await self._send_error(
                "INTERNAL_SERVER_ERROR", "Could not process the event."
            )

    async def _on_message_send(self, payload: dict) -> None:
        client_message_id = payload.get("client_message_id")
        result = await database_sync_to_async(self._persist_text)(
            content=payload.get("content", ""),
            reply_to_message_id=payload.get("reply_to_message_id"),
        )
        if result.failed:
            await self._send_error(result.error_code, result.error_message)
            return
        # Ack is sender-only (maps the client's temp id to the server id). The
        # message.new broadcast is emitted by MessageService post-commit.
        await self._send_event(
            "message.ack",
            {
                "client_message_id": client_message_id,
                "message_id": str(result.data.id),
            },
        )

    async def _on_chat_read(self, payload: dict) -> None:
        last_read = payload.get("last_read_message_id")
        if not last_read:
            await self._send_error("INVALID_PAYLOAD", "last_read_message_id required.")
            return
        result = await database_sync_to_async(self._mark_read)(str(last_read))
        if result.failed:
            await self._send_error(result.error_code, result.error_message)

    async def _on_message_viewed(self, payload: dict) -> None:
        message_id = payload.get("message_id")
        if not message_id:
            await self._send_error("INVALID_PAYLOAD", "message_id required.")
            return
        result = await database_sync_to_async(self._mark_viewed)(str(message_id))
        if result.failed:
            await self._send_error(result.error_code, result.error_message)

    async def _on_typing_start(self, payload: dict) -> None:
        await self._set_typing(is_typing=True)

    async def _on_typing_stop(self, payload: dict) -> None:
        await self._set_typing(is_typing=False)

    async def _on_presence_heartbeat(self, payload: dict) -> None:
        await database_sync_to_async(cache.set)(
            self._presence_key(), "1", PRESENCE_TTL_SECONDS
        )

    # -- Group broadcast forwarding ----------------------------------------

    async def chat_broadcast(self, message: dict) -> None:
        """Forward a group broadcast to this socket (honoring exclusions)."""
        exclude = message.get("exclude_user_id")
        if exclude and str(self.user.id) == exclude:
            return
        await self.send_json(
            {
                "event": message["event"],
                "payload": message["payload"],
                "timestamp": message.get("timestamp"),
            }
        )

    # -- Ephemeral state ----------------------------------------------------

    async def _set_presence(self, *, online: bool) -> None:
        if online:
            await database_sync_to_async(cache.set)(
                self._presence_key(), "1", PRESENCE_TTL_SECONDS
            )
        else:
            await database_sync_to_async(cache.delete)(self._presence_key())
        # Presence is visible only to the other participant.
        await self._group_broadcast(
            "presence.update",
            {"user_id": str(self.user.id), "is_online": online},
            exclude_user_id=str(self.user.id),
        )

    async def _set_typing(self, *, is_typing: bool) -> None:
        key = f"typing:chat:{self.chat_id}:{self.user.id}"
        if is_typing:
            await database_sync_to_async(cache.set)(key, "1", TYPING_TTL_SECONDS)
        else:
            await database_sync_to_async(cache.delete)(key)
        await self._group_broadcast(
            "typing.status",
            {"user_id": str(self.user.id), "is_typing": is_typing},
            exclude_user_id=str(self.user.id),
        )

    # -- Outbound helpers ---------------------------------------------------

    async def _send_event(self, event: str, payload: dict) -> None:
        await self.send_json(
            {
                "event": event,
                "payload": payload,
                "timestamp": timezone.now().isoformat(),
            }
        )

    async def _send_error(self, code: str, message: str) -> None:
        await self._send_event("error", {"code": code, "message": message})

    async def _group_broadcast(
        self, event: str, payload: dict, *, exclude_user_id: str | None = None
    ) -> None:
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.broadcast",
                "event": event,
                "payload": payload,
                "exclude_user_id": exclude_user_id,
                "timestamp": timezone.now().isoformat(),
            },
        )

    def _presence_key(self) -> str:
        return f"presence:user:{self.user.id}"

    # -- Synchronous DB work (run in a thread) ------------------------------

    def _persist_text(self, *, content: str, reply_to_message_id):
        return MessageService().send_text(
            chat_id=self.chat_id,
            sender=self.user,
            content=content,
            reply_to_message_id=(
                str(reply_to_message_id) if reply_to_message_id else None
            ),
        )

    def _mark_read(self, last_read_message_id: str):
        return ChatService().mark_read(
            user=self.user,
            chat_id=self.chat_id,
            last_read_message_id=last_read_message_id,
        )

    def _mark_viewed(self, message_id: str):
        return MessageService().mark_viewed(message_id=message_id, user=self.user)

    @staticmethod
    def _is_authenticated(user) -> bool:
        return (
            user is not None
            and not isinstance(user, AnonymousUser)
            and getattr(user, "is_authenticated", False)
        )

    @database_sync_to_async
    def _chat_exists(self, chat_id: str) -> bool:
        return Chat.objects.filter(id=chat_id).exists()

    @database_sync_to_async
    def _is_participant(self, chat_id: str, user_id) -> bool:
        return ChatParticipant.objects.filter(chat_id=chat_id, user_id=user_id).exists()
