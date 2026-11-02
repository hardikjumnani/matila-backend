"""
Chat push service.

Turns chat events (new message, reaction) into identity-safe phone pushes for the
OTHER user, enqueued post-commit onto the ``push_chat_event`` task. Carries no real
name and no message text: the label is the sender's per-chat anonymous alias and the
body is generic. See docs/CHAT_PUSH_NOTIFICATIONS_PLAN.md.
"""

from __future__ import annotations

import json
import logging

from django.db import transaction

from apps.chats.aliases import anonymous_alias
from apps.messaging.enums import MessageType

logger = logging.getLogger(__name__)


class ChatPushService:
    def __init__(self, *, chat_service=None) -> None:
        if chat_service is None:
            from apps.chats.services.chat_service import ChatService

            chat_service = ChatService()
        self._chats = chat_service

    def notify_new_message(self, message) -> None:
        """Push the other participant(s) about a new message. No-op for system
        messages (no sender)."""
        sender_id = message.sender_id
        if sender_id is None:
            return
        chat = message.chat
        chat_id = str(chat.id)
        alias = anonymous_alias(chat_id, str(sender_id))
        body = (
            "You got a photo"
            if message.message_type == MessageType.IMAGE
            else "You got a message"
        )
        data = {
            "type": "chat.message",
            "chat_id": chat_id,
            "message_id": str(message.id),
            "alias": alias,
            # Deep-link contract already shipped on FE (bridge Phase 7): tap ->
            # OPEN_CHAT with a JSON-string action_payload.
            "action_type": "OPEN_CHAT",
            "action_payload": json.dumps({"chat_id": chat_id}),
        }
        for recipient_id in self._chats.other_participant_ids(chat, sender_id):
            self._enqueue(str(recipient_id), "message", chat_id, alias, body, data)

    def notify_reaction(self, message, reactor, emoji: str) -> None:
        """Push the message author when someone else reacts to their message."""
        author_id = message.sender_id
        if author_id is None or str(author_id) == str(reactor.id):
            return
        chat = message.chat
        chat_id = str(chat.id)
        alias = anonymous_alias(chat_id, str(reactor.id))
        body = f"Reacted {emoji} to your message"
        data = {
            "type": "chat.reaction",
            "chat_id": chat_id,
            "message_id": str(message.id),
            "alias": alias,
            "action_type": "OPEN_CHAT",
            "action_payload": json.dumps({"chat_id": chat_id}),
        }
        self._enqueue(str(author_id), "reaction", chat_id, alias, body, data)

    @staticmethod
    def _enqueue(recipient_id, kind, chat_id, title, body, data) -> None:
        def _dispatch() -> None:
            try:
                from apps.notifications.tasks import push_chat_event

                push_chat_event.delay(recipient_id, kind, chat_id, title, body, data)
            except Exception as exc:  # noqa: BLE001 — broker down must not break send.
                logger.warning(
                    "Could not enqueue chat push (%s) for %s: %s",
                    kind, recipient_id, exc,
                )

        transaction.on_commit(_dispatch)
