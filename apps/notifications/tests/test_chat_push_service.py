"""Tests for ChatPushService: identity-safe enqueue of chat pushes."""

from __future__ import annotations

import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.chats.aliases import anonymous_alias
from apps.chats.enums import ChatPhase, ChatStatus
from apps.chats.models import Chat, ChatParticipant
from apps.configuration.constants import FeatureFlagKey
from apps.configuration.models import FeatureFlag
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
        cache.clear()
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

    # -- Post-reveal real name ---------------------------------------------

    def _reveal(self, status=ChatStatus.REVEALED) -> None:
        self.chat.current_phase = ChatPhase.REVEALED
        self.chat.status = status
        self.chat.save(update_fields=["current_phase", "status"])

    def _enqueue_args(self, call):
        return dict(
            zip(
                ("recipient_id", "kind", "chat_id", "title", "body", "data"),
                call.args,
            )
        )

    def test_revealed_chat_message_shows_real_name(self):
        self._reveal()
        message = self._msg(self.a)
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_new_message(message)
        a = self._enqueue_args(task.delay.call_args)
        self.assertEqual(a["title"], "Hardik Jumnani")
        self.assertEqual(a["data"]["display_name"], "Hardik Jumnani")
        # alias still present for backward-compat.
        self.assertEqual(
            a["data"]["alias"], anonymous_alias(str(self.chat.id), str(self.a.id))
        )

    def test_revealed_reaction_shows_real_name(self):
        self._reveal()
        message = self._msg(self.a)
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_reaction(message, self.b, "\U0001F602")  # B reacts
        a = self._enqueue_args(task.delay.call_args)
        self.assertEqual(a["title"], "Isha Roy")
        self.assertEqual(a["data"]["display_name"], "Isha Roy")

    def test_ended_after_reveal_still_shows_real_name(self):
        # current_phase stays REVEALED after the chat ends/expires.
        self._reveal(status=ChatStatus.ENDED)
        message = self._msg(self.a)
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_new_message(message)
        self.assertEqual(self._enqueue_args(task.delay.call_args)["title"], "Hardik Jumnani")

    def test_flag_off_keeps_alias_even_when_revealed(self):
        self._reveal()
        FeatureFlag.objects.create(
            key=FeatureFlagKey.REVEAL_REAL_NAME_PUSH_ENABLED, value=False
        )
        cache.clear()
        message = self._msg(self.a)
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_new_message(message)
        a = self._enqueue_args(task.delay.call_args)
        self.assertEqual(a["title"], anonymous_alias(str(self.chat.id), str(self.a.id)))
        self.assertNotIn("display_name", a["data"])

    def test_revealed_blank_name_falls_back_to_alias(self):
        nameless = _user("")  # no full_name
        ChatParticipant.objects.create(chat=self.chat, user=nameless)
        self._reveal()
        message = self._msg(nameless)
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_new_message(message)
        a = self._enqueue_args(task.delay.call_args)
        self.assertEqual(
            a["title"], anonymous_alias(str(self.chat.id), str(nameless.id))
        )
        self.assertNotIn("display_name", a["data"])

    def test_anonymous_chat_still_aliased(self):
        # No reveal: default ANONYMOUS phase keeps the alias and omits display_name.
        message = self._msg(self.a)
        with mock.patch(_TASK) as task, self.captureOnCommitCallbacks(execute=True):
            self.svc.notify_new_message(message)
        a = self._enqueue_args(task.delay.call_args)
        self.assertEqual(a["title"], anonymous_alias(str(self.chat.id), str(self.a.id)))
        self.assertNotIn("display_name", a["data"])
