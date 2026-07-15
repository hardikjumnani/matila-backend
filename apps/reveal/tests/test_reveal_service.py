"""Tests for RevealService (real chat/config; notifications mocked)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.configuration.constants import FeatureFlagKey
from apps.configuration.models import FeatureFlag
from apps.configuration.services.configuration_service import ConfigurationService
from apps.reveal.enums import RevealIntentStatus
from apps.reveal.models import RevealIntent
from apps.reveal.services.reveal_service import RevealService
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class RevealServiceTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.chats = ChatService(notification_service=mock.MagicMock())
        self.service = RevealService(
            chat_service=self.chats,
            configuration_service=ConfigurationService(),
            notification_service=mock.MagicMock(),
        )
        self.a = _user()
        self.b = _user()
        self.chat = self.chats.create_chat(self.a, self.b).data
        self._make_eligible()

    def _make_eligible(self) -> None:
        Chat.objects.filter(id=self.chat.id).update(message_count=100)

    def test_not_eligible_rejected(self) -> None:
        Chat.objects.filter(id=self.chat.id).update(message_count=0)
        result = self.service.submit_intent(chat_id=str(self.chat.id), user=self.a)
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_single_intent_is_not_mutual(self) -> None:
        result = self.service.submit_intent(chat_id=str(self.chat.id), user=self.a)
        self.assertTrue(result.success)
        self.assertFalse(result.data["mutual"])

    def test_mutual_intent_requires_payment(self) -> None:
        self.service.submit_intent(chat_id=str(self.chat.id), user=self.a)
        result = self.service.submit_intent(chat_id=str(self.chat.id), user=self.b)
        self.assertTrue(result.data["mutual"])
        self.assertTrue(result.data["payment_required"])

    def test_reveal_disabled_flag(self) -> None:
        FeatureFlag.objects.create(key=FeatureFlagKey.REVEAL_ENABLED, value=False)
        cache.clear()
        result = self.service.submit_intent(chat_id=str(self.chat.id), user=self.a)
        self.assertEqual(result.error_code, "FORBIDDEN")

    def test_non_participant_forbidden(self) -> None:
        result = self.service.submit_intent(chat_id=str(self.chat.id), user=_user())
        self.assertEqual(result.error_code, "FORBIDDEN")

    def test_mutual_pay_completes_reveal(self) -> None:
        self.service.submit_intent(chat_id=str(self.chat.id), user=self.a)
        self.service.submit_intent(chat_id=str(self.chat.id), user=self.b)

        first = self.service.mark_intent_paid(chat_id=str(self.chat.id), user=self.a)
        self.assertFalse(first.data["completed"])

        second = self.service.mark_intent_paid(chat_id=str(self.chat.id), user=self.b)
        self.assertTrue(second.data["completed"])

        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, ChatStatus.REVEALED)
        self.assertEqual(
            RevealIntent.objects.filter(
                chat=self.chat, status=RevealIntentStatus.COMPLETED
            ).count(),
            2,
        )

    def test_mark_paid_without_intent(self) -> None:
        result = self.service.mark_intent_paid(chat_id=str(self.chat.id), user=self.a)
        self.assertEqual(result.error_code, "VALIDATION_ERROR")
