"""Tests for ChatService lifecycle transitions."""

from __future__ import annotations

import uuid
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.chats.enums import ChatPhase, ChatStatus, EndReason, ParticipantStatus
from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class ChatServiceTests(TestCase):
    def setUp(self) -> None:
        self.notifications = mock.MagicMock()
        self.service = ChatService(notification_service=self.notifications)
        self.a = _user()
        self.b = _user()

    def _chat(self) -> Chat:
        return self.service.create_chat(self.a, self.b).data

    def test_create_chat_sets_anonymous_window(self) -> None:
        result = self.service.create_chat(self.a, self.b)
        self.assertTrue(result.success)
        chat = result.data
        self.assertEqual(chat.status, ChatStatus.ACTIVE)
        self.assertEqual(chat.current_phase, ChatPhase.ANONYMOUS)
        self.assertEqual(chat.participants.count(), 2)
        delta = chat.current_phase_ends_at - chat.created_at
        self.assertAlmostEqual(delta.total_seconds(), 48 * 3600, delta=5)

    @override_settings(CHAT_ANONYMOUS_WINDOW_SECONDS_OVERRIDE=120)
    def test_create_chat_honors_time_compression(self) -> None:
        chat = self.service.create_chat(self.a, self.b).data
        delta = chat.current_phase_ends_at - chat.created_at
        self.assertAlmostEqual(delta.total_seconds(), 120, delta=5)

    def test_create_chat_rejects_same_user(self) -> None:
        self.assertTrue(self.service.create_chat(self.a, self.a).failed)

    def test_create_chat_rejects_when_user_already_in_chat(self) -> None:
        self._chat()
        result = self.service.create_chat(self.a, _user())
        self.assertEqual(result.error_code, "CONFLICT")

    def test_has_and_get_active_chat(self) -> None:
        chat = self._chat()
        self.assertTrue(self.service.has_active_chat(self.a))
        self.assertEqual(self.service.get_active_chat(self.b).id, chat.id)

    def test_record_new_message_increments_count(self) -> None:
        chat = self._chat()
        now = timezone.now()
        self.service.record_new_message(chat, sent_at=now)
        self.service.record_new_message(chat, sent_at=now)
        chat.refresh_from_db()
        self.assertEqual(chat.message_count, 2)
        self.assertIsNotNone(chat.last_message_at)

    def test_expire_keeps_phase_anonymous(self) -> None:
        chat = self._chat()
        result = self.service.expire_chat(str(chat.id))
        self.assertEqual(result.data.status, ChatStatus.EXPIRED)
        self.assertEqual(result.data.current_phase, ChatPhase.ANONYMOUS)
        self.assertEqual(self.notifications.create_notification.call_count, 2)

    def test_expire_is_idempotent_on_ended_chat(self) -> None:
        chat = self._chat()
        self.service.end_chat(str(chat.id), reason=EndReason.USER_EXIT)
        result = self.service.expire_chat(str(chat.id))
        self.assertEqual(result.data.status, ChatStatus.ENDED)

    def test_extend_chat(self) -> None:
        chat = self._chat()
        self.service.expire_chat(str(chat.id))
        result = self.service.extend_chat(str(chat.id))
        self.assertEqual(result.data.status, ChatStatus.EXTENDED)
        self.assertEqual(result.data.anonymous_chat_extension_count, 1)
        self.assertGreater(result.data.current_phase_ends_at, timezone.now())

    def test_mark_revealed(self) -> None:
        chat = self._chat()
        result = self.service.mark_revealed(str(chat.id))
        self.assertEqual(result.data.status, ChatStatus.REVEALED)
        self.assertEqual(result.data.current_phase, ChatPhase.REVEALED)

    def test_mark_revealed_fails_on_ended(self) -> None:
        chat = self._chat()
        self.service.end_chat(str(chat.id), reason=EndReason.REPORT)
        self.assertEqual(
            self.service.mark_revealed(str(chat.id)).error_code, "CONFLICT"
        )

    def test_end_chat(self) -> None:
        chat = self._chat()
        result = self.service.end_chat(str(chat.id), reason=EndReason.REPORT)
        self.assertEqual(result.data.status, ChatStatus.ENDED)
        self.assertEqual(result.data.end_reason, EndReason.REPORT)
        self.assertIsNotNone(result.data.ended_at)
        self.assertFalse(self.service.is_writable(result.data))

    def test_leave_chat_marks_left_and_ends(self) -> None:
        chat = self._chat()
        result = self.service.leave_chat(user=self.a, chat_id=str(chat.id))
        self.assertEqual(result.data.status, ChatStatus.ENDED)
        self.assertEqual(result.data.end_reason, EndReason.USER_EXIT)
        participant = self.service.get_participant(chat, self.a)
        self.assertEqual(participant.status, ParticipantStatus.LEFT)

    def test_leave_chat_rejects_non_participant(self) -> None:
        chat = self._chat()
        result = self.service.leave_chat(user=_user(), chat_id=str(chat.id))
        self.assertEqual(result.error_code, "FORBIDDEN")

    def test_hide_chat(self) -> None:
        chat = self._chat()
        result = self.service.hide_chat(user=self.a, chat_id=str(chat.id))
        self.assertTrue(result.data.is_chat_hidden)
