"""Tests for ChatPushService: identity-safe enqueue of chat pushes."""

from __future__ import annotations

import uuid
from unittest import mock

from django.test import TestCase

from apps.chats.aliases import anonymous_alias
from apps.chats.models import Chat, ChatParticipant
from apps.messaging.enums import MessageType
from apps.messaging.models import Message
from apps.notifications.services.chat_push_service import ChatPushService
from apps.users.models import User

_TASK = "apps.notifications.tasks.push_chat_event"


def _user(name="") -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        full_name=name,
    )


class ChatPushServiceTests(TestCase):
    def setUp(self) -> None:
        self.a = _user("Hardik Jumnani")   # sender / author
        self.b = _user("Isha Roy")         # recipient
        self.chat = Chat.objects.create()
        ChatParticipant.objects.create(chat=self.chat, user=self.a)
        ChatParticipant.objects.create(chat=self.chat, user=self.b)
        self.svc = ChatPushService()

    def _msg(self, sender, mtype=MessageType.TEXT, text="hey there"):
        return Message.objects.create(
            chat=self.chat, sender=sender, message_type=mtype, text_content=text
        )

    def test_new_message_enqueues_for_other_only_and_is_identity_safe(self):
        message = self._msg(self.a)
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_new_message(message)
        task.delay.assert_called_once()
        args = task.delay.call_args.args
        recipient_id, kind, chat_id, title, body, data = args
        self.assertEqual(recipient_id, str(self.b.id))   # the OTHER user, not sender
        self.assertEqual(kind, "message")
        self.assertEqual(body, "You got a message")
        self.assertEqual(title, anonymous_alias(str(self.chat.id), str(self.a.id)))
        # Identity-safe: no real name, no message text anywhere in the push.
        blob = f"{title} {body} {data}"
        self.assertNotIn("Hardik", blob)
        self.assertNotIn("hey there", blob)
        self.assertEqual(data["type"], "chat.message")
        self.assertEqual(data["action_type"], "OPEN_CHAT")   # FE deep-link contract

    def test_image_message_body(self):
        message = self._msg(self.a, mtype=MessageType.IMAGE, text="")
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_new_message(message)
        self.assertEqual(task.delay.call_args.args[4], "You got a photo")

    def test_system_message_no_push(self):
        message = Message.objects.create(
            chat=self.chat, sender=None, message_type=MessageType.SYSTEM, text_content="x"
        )
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_new_message(message)
        task.delay.assert_not_called()

    def test_reaction_notifies_author_not_reactor(self):
        message = self._msg(self.a)                   # authored by A
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_reaction(message, self.b, "\U0001F602")  # B reacts
        task.delay.assert_called_once()
        recipient_id, kind, _chat_id, title, body, _data = task.delay.call_args.args
        self.assertEqual(recipient_id, str(self.a.id))   # the author
        self.assertEqual(kind, "reaction")
        self.assertIn("Reacted", body)
        self.assertEqual(title, anonymous_alias(str(self.chat.id), str(self.b.id)))

    def test_self_reaction_no_push(self):
        message = self._msg(self.a)
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_reaction(message, self.a, "\U0001F602")  # A reacts to own
        task.delay.assert_not_called()
