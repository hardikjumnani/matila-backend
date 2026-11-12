"""Tests for the send_expiry_reminders scheduled task."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from apps.chats.aliases import anonymous_alias
from apps.chats.enums import ChatPhase, ChatStatus
from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.chats.tasks.reminders import send_expiry_reminders
from apps.common.realtime import chat_presence_key
from apps.configuration.constants import FeatureFlagKey
from apps.configuration.models import FeatureFlag
from apps.notifications.models import Notification
from apps.users.models import User

_NOW = "apps.chats.tasks.reminders.timezone.now"


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class ExpiryRemindersTaskTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.a = _user()
        self.b = _user()
        self.chat = ChatService().create_chat(self.a, self.b).data

    def _set_deadline(self, when) -> None:
        Chat.objects.filter(id=self.chat.id).update(current_phase_ends_at=when)
        self.chat.refresh_from_db()

    def _reminders(self):
        return Notification.objects.filter(type="chat.expiring")

    def test_sends_one_hour_reminder_in_band(self) -> None:
        self._set_deadline(timezone.now() + timedelta(minutes=50))
        sent = send_expiry_reminders()
        self.assertEqual(sent, 1)
        reminders = self._reminders()
        self.assertEqual(reminders.count(), 2)  # both participants
        self.assertIn("about 1 hour", reminders.first().body)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.expiry_reminder_state["sent"], [60])

    def test_reminder_shape_is_identity_safe_and_actionable(self) -> None:
        self._set_deadline(timezone.now() + timedelta(minutes=50))
        send_expiry_reminders()
        n = self._reminders().get(user=self.a)
        # Title is the partner's alias, never a real name.
        self.assertEqual(n.title, anonymous_alias(str(self.chat.id), str(self.b.id)))
        self.assertEqual(n.action_type, "OPEN_CHAT")
        self.assertEqual(n.action_payload["chat_id"], str(self.chat.id))
        self.assertEqual(n.metadata["minutes"], 60)
        self.assertIsNotNone(n.expires_at)

    def test_second_run_same_window_does_not_resend(self) -> None:
        self._set_deadline(timezone.now() + timedelta(minutes=50))
        send_expiry_reminders()
        send_expiry_reminders()
        self.assertEqual(self._reminders().count(), 2)  # not 4

    def test_thirty_min_fires_after_sixty_same_window(self) -> None:
        deadline = timezone.now().replace(microsecond=0) + timedelta(hours=10)
        self._set_deadline(deadline)
        with mock.patch(_NOW, return_value=deadline - timedelta(minutes=50)):
            send_expiry_reminders()  # sends 60
        with mock.patch(_NOW, return_value=deadline - timedelta(minutes=20)):
            send_expiry_reminders()  # sends 30 (60 already in sent)
        reminders = self._reminders()
        self.assertEqual(reminders.count(), 4)  # 2 + 2
        self.assertTrue(reminders.filter(body__contains="about 30 minutes").exists())
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.expiry_reminder_state["sent"], [30, 60])

    def test_missed_hour_window_sends_only_thirty(self) -> None:
        # Remaining is already within 30 min, nothing sent yet: send one "30 min"
        # reminder, not a stale "1 hour" one too.
        self._set_deadline(timezone.now() + timedelta(minutes=25))
        send_expiry_reminders()
        reminders = self._reminders()
        self.assertEqual(reminders.count(), 2)
        self.assertIn("about 30 minutes", reminders.first().body)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.expiry_reminder_state["sent"], [30, 60])
        send_expiry_reminders()  # nothing left to send
        self.assertEqual(self._reminders().count(), 2)

    def test_not_sent_when_beyond_widest_threshold(self) -> None:
        self._set_deadline(timezone.now() + timedelta(minutes=90))
        self.assertEqual(send_expiry_reminders(), 0)
        self.assertEqual(self._reminders().count(), 0)

    def test_skips_non_anonymous_chat(self) -> None:
        Chat.objects.filter(id=self.chat.id).update(
            current_phase=ChatPhase.REVEALED,
            current_phase_ends_at=timezone.now() + timedelta(minutes=50),
        )
        self.assertEqual(send_expiry_reminders(), 0)
        self.assertEqual(self._reminders().count(), 0)

    def test_skips_ended_chat(self) -> None:
        Chat.objects.filter(id=self.chat.id).update(
            status=ChatStatus.ENDED,
            current_phase_ends_at=timezone.now() + timedelta(minutes=50),
        )
        self.assertEqual(send_expiry_reminders(), 0)

    def test_rearms_after_extension(self) -> None:
        deadline = timezone.now().replace(microsecond=0) + timedelta(hours=10)
        self._set_deadline(deadline)
        with mock.patch(_NOW, return_value=deadline - timedelta(minutes=50)):
            send_expiry_reminders()  # 60 for the first window
        # Extension moves the deadline: both reminders re-arm.
        new_deadline = deadline + timedelta(hours=1)
        Chat.objects.filter(id=self.chat.id).update(
            status=ChatStatus.EXTENDED, current_phase_ends_at=new_deadline
        )
        with mock.patch(_NOW, return_value=new_deadline - timedelta(minutes=50)):
            send_expiry_reminders()  # 60 again, for the new window
        self.assertEqual(self._reminders().count(), 4)

    def test_flag_off_sends_nothing(self) -> None:
        FeatureFlag.objects.create(
            key=FeatureFlagKey.CHAT_EXPIRY_REMINDER_ENABLED, value=False
        )
        cache.clear()
        self._set_deadline(timezone.now() + timedelta(minutes=50))
        self.assertEqual(send_expiry_reminders(), 0)
        self.assertEqual(self._reminders().count(), 0)

    def test_presence_suppresses_that_participant(self) -> None:
        self._set_deadline(timezone.now() + timedelta(minutes=50))
        # a is actively reading the chat -> skip a, still remind b.
        cache.set(chat_presence_key(str(self.chat.id), str(self.a.id)), "1", 60)
        send_expiry_reminders()
        reminders = self._reminders()
        self.assertEqual(reminders.count(), 1)
        self.assertEqual(reminders.first().user_id, self.b.id)
