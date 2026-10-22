"""Tests for message reactions (REST + serializer + config + erasure + admin)."""

from __future__ import annotations

import uuid

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat, ChatParticipant
from apps.messaging.enums import MessageType
from apps.messaging.models import Message, MessageReaction
from apps.users.models import User

_HEART = "❤️"
_FIRE = "\U0001F525"


def _user(email=None) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=email or f"{uuid.uuid4().hex}@college.edu",
        full_name="U",
    )


class ReactionApiTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.a = _user()
        self.b = _user()
        self.chat = Chat.objects.create()  # ACTIVE -> writable
        ChatParticipant.objects.create(chat=self.chat, user=self.a)
        ChatParticipant.objects.create(chat=self.chat, user=self.b)
        self.msg = Message.objects.create(
            chat=self.chat, sender=self.b,
            message_type=MessageType.TEXT, text_content="hi",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.a)

    def _url(self, mid=None) -> str:
        return f"/api/v1/messages/{mid or self.msg.id}/reactions"

    def test_set_reaction(self):
        resp = self.client.post(self._url(), {"emoji": _HEART}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            MessageReaction.objects.filter(message=self.msg, user=self.a).count(), 1
        )
        self.assertEqual(
            resp.json()["data"]["reactions"],
            [{"user_id": str(self.a.id), "emoji": _HEART}],
        )

    def test_replace_keeps_single_row(self):
        self.client.post(self._url(), {"emoji": _HEART}, format="json")
        self.client.post(self._url(), {"emoji": _FIRE}, format="json")
        rows = MessageReaction.objects.filter(message=self.msg, user=self.a)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().emoji, _FIRE)

    def test_two_users_two_reactions(self):
        self.client.post(self._url(), {"emoji": _HEART}, format="json")
        other = APIClient()
        other.force_authenticate(user=self.b)
        other.post(self._url(), {"emoji": _FIRE}, format="json")
        self.assertEqual(MessageReaction.objects.filter(message=self.msg).count(), 2)

    def test_remove(self):
        self.client.post(self._url(), {"emoji": _HEART}, format="json")
        resp = self.client.delete(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            MessageReaction.objects.filter(message=self.msg, user=self.a).exists()
        )

    def test_remove_is_idempotent(self):
        self.assertEqual(self.client.delete(self._url()).status_code, 200)

    def test_invalid_emoji(self):
        resp = self.client.post(self._url(), {"emoji": "\U0001F984"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REACTION")

    def test_non_participant_forbidden(self):
        outsider = APIClient()
        outsider.force_authenticate(user=_user())
        resp = outsider.post(self._url(), {"emoji": _HEART}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_system_message_blocked(self):
        sysmsg = Message.objects.create(
            chat=self.chat, sender=None,
            message_type=MessageType.SYSTEM, text_content="revealed",
        )
        resp = self.client.post(self._url(sysmsg.id), {"emoji": _HEART}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_deleted_message_not_found(self):
        self.msg.is_deleted = True
        self.msg.save(update_fields=["is_deleted"])
        resp = self.client.post(self._url(), {"emoji": _HEART}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_read_only_chat_rejected(self):
        self.chat.status = ChatStatus.ENDED
        self.chat.save(update_fields=["status"])
        resp = self.client.post(self._url(), {"emoji": _HEART}, format="json")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "CHAT_READ_ONLY")

    def test_history_includes_reactions(self):
        self.client.post(self._url(), {"emoji": _HEART}, format="json")
        resp = self.client.get(f"/api/v1/chats/{self.chat.id}/messages")
        item = next(
            m for m in resp.json()["data"]["items"] if m["id"] == str(self.msg.id)
        )
        self.assertEqual(item["reactions"], [{"user_id": str(self.a.id), "emoji": _HEART}])

    def test_deleted_message_hides_reactions_in_history(self):
        MessageReaction.objects.create(message=self.msg, user=self.a, emoji=_HEART)
        self.msg.is_deleted = True
        self.msg.save(update_fields=["is_deleted"])
        resp = self.client.get(f"/api/v1/chats/{self.chat.id}/messages")
        item = next(
            m for m in resp.json()["data"]["items"] if m["id"] == str(self.msg.id)
        )
        self.assertEqual(item["reactions"], [])

    def test_erase_deletes_user_reactions(self):
        from apps.users.services.erasure_service import UserErasureService

        MessageReaction.objects.create(message=self.msg, user=self.a, emoji=_HEART)
        summary = UserErasureService().erase(self.a)
        self.assertEqual(summary["reactions_deleted"], 1)
        self.assertFalse(MessageReaction.objects.filter(user=self.a).exists())


class ReactionConfigTests(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_config_exposes_reaction_set(self):
        from apps.configuration.services.configuration_service import (
            ConfigurationService,
        )

        rc = ConfigurationService().get_runtime_config()
        self.assertIn("reactions", rc)
        self.assertEqual(rc["reactions"]["emojis"][0], _HEART)
        self.assertTrue(rc["reactions"]["version"])


@override_settings(ADMIN_EMAILS=["admin@college.edu"])
class ReactionAdminEvidenceTests(TestCase):
    def setUp(self) -> None:
        self.admin = _user("admin@college.edu")
        self.a = _user()
        self.b = _user()
        self.chat = Chat.objects.create()
        ChatParticipant.objects.create(chat=self.chat, user=self.a)
        ChatParticipant.objects.create(chat=self.chat, user=self.b)
        self.msg = Message.objects.create(
            chat=self.chat, sender=self.b,
            message_type=MessageType.TEXT, text_content="hi",
        )
        MessageReaction.objects.create(message=self.msg, user=self.a, emoji=_HEART)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_transcript_shows_reactions_even_when_deleted(self):
        self.msg.is_deleted = True
        self.msg.save(update_fields=["is_deleted"])
        resp = self.client.get(f"/api/v1/admin/chats/{self.chat.id}/messages")
        self.assertEqual(resp.status_code, 200)
        m = next(
            x for x in resp.json()["data"]["messages"] if x["id"] == str(self.msg.id)
        )
        self.assertEqual(m["reactions"], [{"user_id": str(self.a.id), "emoji": _HEART}])
