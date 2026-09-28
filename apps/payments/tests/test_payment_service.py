"""PaymentService tests: Play verification, store bundles, and coin spend."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.payments.enums import PaymentInitiatedFrom, PaymentPurpose
from apps.payments.models import Payment
from apps.payments.services.credit_service import CreditService
from apps.payments.services.payment_service import PaymentService
from apps.reveal.enums import DecisionChoice
from apps.reveal.services.reveal_service import RevealService
from apps.users.enums import Gender
from apps.users.models import User

_VERIFY_PLAY = "apps.payments.gateway_play.verify_product_purchase"


def _user(gender: str) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        gender=gender,
        intent="RELATIONSHIP",
        gender_preferences=[Gender.MALE, Gender.FEMALE],
    )


def _play_stub(**_kwargs):
    return {"purchaseState": 0, "orderId": "GPA." + uuid.uuid4().hex}


@override_settings(PAYMENTS_DEV_BYPASS=True)
class PaymentServiceTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        notif = mock.MagicMock()
        self.chats = ChatService(notification_service=notif)
        self.reveal = RevealService(chat_service=self.chats, notification_service=notif)
        self.credits = CreditService()
        self.service = PaymentService(
            chat_service=self.chats, reveal_service=self.reveal,
            credit_service=self.credits, notification_service=notif,
        )
        self.boy = _user(Gender.MALE)
        self.girl = _user(Gender.FEMALE)
        self.chat = self.chats.create_chat(self.boy, self.girl).data
        Chat.objects.filter(id=self.chat.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )

    def _reach_reveal_payment(self) -> None:
        self.reveal.submit_decision(
            chat_id=str(self.chat.id), user=self.boy, choice=DecisionChoice.REVEAL
        )
        self.reveal.submit_decision(
            chat_id=str(self.chat.id), user=self.girl, choice=DecisionChoice.REVEAL
        )

    def _reach_safe_payment(self) -> None:
        self.reveal.submit_decision(
            chat_id=str(self.chat.id), user=self.boy, choice=DecisionChoice.REVEAL
        )
        self.reveal.submit_decision(
            chat_id=str(self.chat.id), user=self.girl, choice=DecisionChoice.SAFE_REVEAL
        )

    def _verify(self, user, token, product_id, purpose=PaymentPurpose.SAFE_REVEAL):
        return self.service.verify_google_play_purchase(
            user=user, chat_id=str(self.chat.id), purpose=purpose,
            product_id=product_id, purchase_token=token,
            initiated_from=PaymentInitiatedFrom.CHAT_SCREEN,
        )

    # -- verify-purchase context -------------------------------------------

    def test_verify_purchase_requires_active_payment_round(self) -> None:
        result = self._verify(self.boy, "tok", "safe_reveal_male")
        self.assertEqual(result.error_code, "NO_ACTIVE_PAYMENT")

    def test_verify_purchase_records_side(self) -> None:
        self._reach_safe_payment()
        result = self._verify(self.boy, "tok_b", "safe_reveal_male")
        self.assertTrue(result.success)
        self.assertEqual(result.data.amount_in_paise, 2900)
        self.assertTrue(self.reveal.has_paid(self.chat, self.boy))

    def test_verify_purchase_idempotent_on_token(self) -> None:
        self._reach_safe_payment()
        first = self._verify(self.boy, "tok_same", "safe_reveal_male")
        second = self._verify(self.boy, "tok_same", "safe_reveal_male")
        self.assertEqual(first.data.id, second.data.id)
        self.assertEqual(Payment.objects.filter(user=self.boy).count(), 1)

    def test_verify_purchase_already_paid_this_cycle(self) -> None:
        self._reach_safe_payment()
        self._verify(self.boy, "tok_b1", "safe_reveal_male")  # boy pays his side
        # A fresh token, same cycle → distinct ALREADY_PAID code (not idempotent reuse).
        result = self._verify(self.boy, "tok_b2", "safe_reveal_male")
        self.assertEqual(result.error_code, "ALREADY_PAID")

    def test_reveal_purpose_not_purchasable(self) -> None:
        self._reach_reveal_payment()
        result = self._verify(
            self.boy, "tok", "safe_reveal_male", purpose=PaymentPurpose.REVEAL
        )
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    # -- store bundle -> coins ---------------------------------------------

    def test_purchase_bundle_grants_coins(self) -> None:
        result = self.service.purchase_bundle(
            user=self.boy, product_id="standard_reveal_3",
            purchase_token="tok_" + uuid.uuid4().hex,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["coins_added"], 3)
        self.assertEqual(self.credits.get_balances(self.boy)["reveal_coins"], 3)

    def test_purchase_bundle_idempotent_on_token(self) -> None:
        token = "tok_" + uuid.uuid4().hex
        self.service.purchase_bundle(
            user=self.boy, product_id="standard_reveal_5", purchase_token=token
        )
        self.service.purchase_bundle(
            user=self.boy, product_id="standard_reveal_5", purchase_token=token
        )
        self.assertEqual(self.credits.get_balances(self.boy)["reveal_coins"], 5)

    def test_purchase_unknown_product_rejected(self) -> None:
        result = self.service.purchase_bundle(
            user=self.boy, product_id="not_a_product", purchase_token="t"
        )
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    # -- pay with coin ------------------------------------------------------

    def test_pay_with_coin_spends_balance(self) -> None:
        self.credits.credit(
            user=self.boy, coin_type="REVEAL", amount=1,
            reason="ADMIN_ADJUST", idempotency_key="seed",
        )
        self._reach_reveal_payment()
        result = self.service.pay_with_coin(
            user=self.boy, chat_id=str(self.chat.id), purpose=PaymentPurpose.REVEAL
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["balances"]["reveal_coins"], 0)
        self.assertTrue(self.reveal.has_paid(self.chat, self.boy))

    def test_pay_with_coin_requires_active_round(self) -> None:
        self.credits.credit(
            user=self.boy, coin_type="REVEAL", amount=1,
            reason="ADMIN_ADJUST", idempotency_key="seed",
        )
        result = self.service.pay_with_coin(
            user=self.boy, chat_id=str(self.chat.id), purpose=PaymentPurpose.REVEAL
        )
        self.assertEqual(result.error_code, "NO_ACTIVE_PAYMENT")
