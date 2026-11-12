"""Tests for the purge_user_data management command."""

from __future__ import annotations

import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.colleges.models import College
from apps.configuration.models import AppConfig, FeatureFlag
from apps.messaging.models import Message
from apps.messaging.services.message_service import MessageService
from apps.payments.enums import CoinLedgerReason
from apps.payments.models import CoinLedger, Wallet
from apps.payments.services.credit_service import CreditService
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        full_name="Tester",
    )


class PurgeUserDataTests(TestCase):
    def _seed(self):
        a, b = _user(), _user()
        chat = ChatService().create_chat(a, b).data
        MessageService().send_text(chat_id=str(chat.id), sender=a, content="hi")
        # Wallet + CoinLedger exercise the PROTECT-before-user ordering.
        CreditService().credit(
            user=a, amount=10, reason=CoinLedgerReason.ADMIN_ADJUST,
            idempotency_key="seed-" + uuid.uuid4().hex,
        )
        # Config rows with updated_by set, to prove they survive (SET_NULL) and
        # pricing is preserved.
        FeatureFlag.objects.create(key="x_test_flag", value=True, updated_by=a)
        AppConfig.objects.create(
            key="x_test_pricing", value={"price_paise": 5900}, updated_by=a
        )
        return a, b, chat

    def test_wipe_removes_all_user_data_keeps_config(self) -> None:
        self._seed()
        colleges_before = College.objects.count()
        self.assertTrue(colleges_before >= 1)

        call_command("purge_user_data", confirm="WIPE")

        # Everything user/transactional is gone.
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Chat.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(Wallet.objects.count(), 0)
        self.assertEqual(CoinLedger.objects.count(), 0)
        # Reference + config survive; pricing config preserved.
        self.assertEqual(College.objects.count(), colleges_before)
        self.assertTrue(FeatureFlag.objects.filter(key="x_test_flag").exists())
        pricing = AppConfig.objects.get(key="x_test_pricing")
        self.assertEqual(pricing.value, {"price_paise": 5900})
        # updated_by was SET_NULL, not deleted with the user.
        self.assertIsNone(pricing.updated_by_id)
        self.assertIsNone(FeatureFlag.objects.get(key="x_test_flag").updated_by_id)

    def test_dry_run_deletes_nothing(self) -> None:
        self._seed()
        call_command("purge_user_data", dry_run=True)
        self.assertGreater(User.objects.count(), 0)
        self.assertGreater(Chat.objects.count(), 0)

    def test_refuses_without_confirmation(self) -> None:
        self._seed()
        with self.assertRaises(CommandError):
            call_command("purge_user_data")
        self.assertGreater(User.objects.count(), 0)

    def test_wrong_confirm_token_refuses(self) -> None:
        self._seed()
        with self.assertRaises(CommandError):
            call_command("purge_user_data", confirm="wipe")  # case-sensitive
        self.assertGreater(User.objects.count(), 0)
