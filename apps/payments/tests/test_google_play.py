"""Google Play purchase-verification tests (Play API mocked), new model."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.payments.enums import PaymentInitiatedFrom, PaymentProvider, PaymentPurpose
from apps.payments.gateway_play import InvalidPurchase
from apps.payments.models import Payment
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


def _stub(**_kwargs):
    return {"purchaseState": 0, "orderId": "GPA." + uuid.uuid4().hex}


class GooglePlayPaymentTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        notif = mock.MagicMock()
        self.chats = ChatService(notification_service=notif)
        self.reveal = RevealService(chat_service=self.chats, notification_service=notif)
        self.service = PaymentService(
            chat_service=self.chats, reveal_service=self.reveal, notification_service=notif
        )
        self.boy = _user(Gender.MALE)
        self.girl = _user(Gender.FEMALE)
        self.chat = self.chats.create_chat(self.boy, self.girl).data
        Chat.objects.filter(id=self.chat.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
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
            user=user,
            chat_id=str(self.chat.id),
            purpose=purpose,
            product_id=product_id,
            purchase_token=token,
            initiated_from=PaymentInitiatedFrom.CHAT_SCREEN,
        )

    def test_safe_reveal_both_pay_enters_safe_decision(self) -> None:
        self._reach_safe_payment()
        with mock.patch(_VERIFY_PLAY, side_effect=_stub):
            self._verify(self.boy, "tok_b", "safe_reveal_male")
            self.chat.refresh_from_db()
            self.assertEqual(self.chat.status, ChatStatus.ACTIVE)  # not revealed
            self._verify(self.girl, "tok_g", "safe_reveal_female")
        payment = Payment.objects.get(user=self.boy, chat=self.chat)
        self.assertEqual(payment.provider, PaymentProvider.GOOGLE_PLAY)
        self.assertEqual(payment.amount_in_paise, 2900)  # male safe reveal price

    def test_safe_reveal_wrong_sku_for_gender_rejected(self) -> None:
        self._reach_safe_payment()
        with mock.patch(_VERIFY_PLAY, side_effect=_stub):
            # Boy tries the female SKU.
            result = self._verify(self.boy, "tok", "safe_reveal_female")
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_purchase_idempotent_on_token(self) -> None:
        self._reach_safe_payment()
        with mock.patch(_VERIFY_PLAY, side_effect=_stub):
            first = self._verify(self.boy, "tok_same", "safe_reveal_male")
            second = self._verify(self.boy, "tok_same", "safe_reveal_male")
        self.assertEqual(first.data.id, second.data.id)
        self.assertEqual(Payment.objects.filter(user=self.boy).count(), 1)

    def test_product_purpose_mismatch_rejected(self) -> None:
        self._reach_safe_payment()
        result = self._verify(self.boy, "tok", "chat_extension")
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_invalid_purchase_rejected(self) -> None:
        self._reach_safe_payment()
        with mock.patch(_VERIFY_PLAY, side_effect=InvalidPurchase()):
            result = self._verify(self.boy, "tok", "safe_reveal_male")
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_bundle_sku_rejected_on_chat_endpoint(self) -> None:
        self._reach_safe_payment()
        result = self._verify(
            self.boy, "tok", "standard_reveal_3", purpose=PaymentPurpose.CREDIT_PURCHASE
        )
        self.assertEqual(result.error_code, "VALIDATION_ERROR")
