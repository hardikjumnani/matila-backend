"""
WebSocket tests for ChatConsumer.

Uses the in-memory channel layer and injects ``scope['user']`` directly (the
Firebase middleware is tested separately). TransactionTestCase is required so
that transaction.on_commit broadcasts actually fire (a wrapped TestCase would
swallow them).
"""

from __future__ import annotations

import uuid

from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.test import TransactionTestCase

from apps.chats.enums import EndReason
from apps.chats.services.chat_service import ChatService
from apps.users.models import User
from config.routing import websocket_urlpatterns


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class ChatConsumerTests(TransactionTestCase):
    def setUp(self) -> None:
        self.a = _user()
        self.b = _user()
        self.outsider = _user()
        self.chat = ChatService().create_chat(self.a, self.b).data
        self.app = URLRouter(websocket_urlpatterns)
        self.path = f"/ws/chat/{self.chat.id}/"

    async def _connect(self, user):
        communicator = WebsocketCommunicator(self.app, self.path)
        communicator.scope["user"] = user
        connected, code = await communicator.connect()
        return communicator, connected, code

    async def _await_event(self, communicator, event, tries=6):
        for _ in range(tries):
            message = await communicator.receive_json_from(timeout=2)
            if message["event"] == event:
                return message
        raise AssertionError(f"Event {event} not received")

    # -- Connection lifecycle ----------------------------------------------

    async def test_rejects_anonymous(self) -> None:
        communicator = WebsocketCommunicator(self.app, self.path)
        communicator.scope["user"] = AnonymousUser()
        connected, code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4001)

    async def test_rejects_non_participant(self) -> None:
        _, connected, code = await self._connect(self.outsider)
        self.assertFalse(connected)
        self.assertEqual(code, 4002)

    async def test_rejects_invalid_chat(self) -> None:
        communicator = WebsocketCommunicator(self.app, f"/ws/chat/{uuid.uuid4()}/")
        communicator.scope["user"] = self.a
        connected, code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4004)

    async def test_participant_connects(self) -> None:
        communicator, connected, _ = await self._connect(self.a)
        self.assertTrue(connected)
        await communicator.disconnect()

    # -- Messaging ----------------------------------------------------------

    async def test_message_send_acks_and_broadcasts(self) -> None:
        comm_a, _, _ = await self._connect(self.a)
        comm_b, _, _ = await self._connect(self.b)

        await comm_a.send_json_to(
            {
                "event": "message.send",
                "payload": {"client_message_id": "t1", "content": "hello"},
            }
        )
        ack = await self._await_event(comm_a, "message.ack")
        self.assertEqual(ack["payload"]["client_message_id"], "t1")
        self.assertTrue(ack["payload"]["message_id"])

        new_for_b = await self._await_event(comm_b, "message.new")
        self.assertEqual(new_for_b["payload"]["message"]["text_content"], "hello")

        await comm_a.disconnect()
        await comm_b.disconnect()

    async def test_read_only_chat_rejects_send(self) -> None:
        await database_sync_to_async(ChatService().end_chat)(
            str(self.chat.id), reason=EndReason.USER_EXIT
        )
        comm_a, _, _ = await self._connect(self.a)
        await comm_a.send_json_to(
            {"event": "message.send", "payload": {"content": "hi"}}
        )
        error = await self._await_event(comm_a, "error")
        self.assertEqual(error["payload"]["code"], "CHAT_READ_ONLY")
        await comm_a.disconnect()

    async def test_chat_read_broadcasts_to_other(self) -> None:
        comm_a, _, _ = await self._connect(self.a)
        comm_b, _, _ = await self._connect(self.b)
        # a sends a message so there is a message id to read.
        await comm_a.send_json_to(
            {
                "event": "message.send",
                "payload": {"client_message_id": "t", "content": "hi"},
            }
        )
        ack = await self._await_event(comm_a, "message.ack")
        message_id = ack["payload"]["message_id"]

        # b marks it read -> a receives the read receipt.
        await comm_b.send_json_to(
            {"event": "chat.read", "payload": {"last_read_message_id": message_id}}
        )
        receipt = await self._await_event(comm_a, "chat.read")
        self.assertEqual(receipt["payload"]["user_id"], str(self.b.id))

        await comm_a.disconnect()
        await comm_b.disconnect()

    # -- Typing -------------------------------------------------------------

    async def test_typing_visible_to_other_only(self) -> None:
        comm_a, _, _ = await self._connect(self.a)
        comm_b, _, _ = await self._connect(self.b)
        await comm_a.send_json_to({"event": "typing.start", "payload": {}})
        status = await self._await_event(comm_b, "typing.status")
        self.assertTrue(status["payload"]["is_typing"])
        self.assertEqual(status["payload"]["user_id"], str(self.a.id))
        await comm_a.disconnect()
        await comm_b.disconnect()

    async def test_unknown_event_errors(self) -> None:
        comm_a, _, _ = await self._connect(self.a)
        await comm_a.send_json_to({"event": "does.not.exist", "payload": {}})
        error = await self._await_event(comm_a, "error")
        self.assertEqual(error["payload"]["code"], "INVALID_PAYLOAD")
        await comm_a.disconnect()
