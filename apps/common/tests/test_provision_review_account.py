"""Tests for the provision_review_account management command (AI_BRIDGE [00079])."""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.chats.services.chat_service import ChatService
from apps.payments.services.credit_service import CreditService
from apps.users.enums import AccountStatus, VerificationStatus
from apps.users.models import User
from apps.users.services.auth_service import AuthService

_SEND = "apps.messaging.services.message_service.MessageService.send_text"


@override_settings(
    REVIEW_DEMO_UID="demo-uid", REVIEW_DEMO_EMAIL="appreview@matila.demo"
)
class ProvisionReviewAccountTests(TestCase):
    def _run(self, *args: str) -> None:
        with mock.patch(_SEND, return_value=None):
            call_command(
                "provision_review_account", "--skip-firebase", *args,
                stdout=StringIO(), stderr=StringIO(),
            )

    def test_provisions_demo_user_routed_to_home(self) -> None:
        self._run("--coins", "25")
        user = User.objects.get(firebase_uid="demo-uid")
        self.assertTrue(user.is_demo)
        self.assertEqual(user.verification_status, VerificationStatus.APPROVED)
        self.assertEqual(user.account_status, AccountStatus.ACTIVE)
        self.assertIsNotNone(user.onboarding_completed_at)
        # Fully provisioned => the reviewer lands straight on HOME.
        self.assertEqual(
            AuthService()._determine_next_action(user).value, "GO_HOME"
        )

    def test_grants_coins_and_seeds_an_active_chat(self) -> None:
        self._run("--coins", "25")
        user = User.objects.get(firebase_uid="demo-uid")
        self.assertEqual(CreditService().get_balances(user)["coins"], 25)
        self.assertIsNotNone(ChatService().get_open_anonymous_chat(user))
        # The partner is itself an isolated demo account.
        partner = User.objects.get(firebase_uid="matila-review-demo-partner")
        self.assertTrue(partner.is_demo)

    def test_is_idempotent(self) -> None:
        self._run("--coins", "25")
        self._run("--coins", "25")
        self.assertEqual(User.objects.filter(is_demo=True).count(), 2)  # user + partner
        user = User.objects.get(firebase_uid="demo-uid")
        # Coins topped up once, not stacked; exactly one open chat.
        self.assertEqual(CreditService().get_balances(user)["coins"], 25)
        from apps.chats.models import ChatParticipant

        self.assertEqual(
            ChatParticipant.objects.filter(user=user).count(), 1
        )
