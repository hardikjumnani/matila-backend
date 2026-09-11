"""Tests for the Google Play purchase-verification path (Play API mocked)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.chats.enums import ChatStatus
from apps.chats.services.chat_service import ChatService
from apps.payments.enums import (
    PaymentInitiatedFrom,
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
)
from apps.payments.gateway_play import InvalidPurchase
from apps.payments.models import Payment
from apps.payments.services.payment_service import PaymentService
from apps.reveal.services.reveal_service import RevealService
from apps.users.models import User

_VERIFY_PLAY = "apps.payments.gateway_play.verify_product_purchase"


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


def _purchase_stub(**_kwargs):
    return {"purchaseState": 0, "orderId": "GPA." + uuid.uuid4().hex}


class GooglePlayPaymentTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.chats = ChatService(notification_service=mock.MagicMock())
        self.reveal = RevealService(
            chat_service=self.chats, notification_service=mock.MagicMock()
        )
        self.service = PaymentService(
            chat_service=self.chats,
            reveal_service=self.reveal,
            notification_service=mock.MagicMock(),
        )
        self.a = _user()
        self.b = _user()
        self.chat = self.chats.create_chat(self.a, self.b).data
        from apps.chats.models import Chat

        Chat.objects.filter(id=self.chat.id).update(message_count=100)

    def _mutual(self) -> None:
        self.reveal.submit_intent(chat_id=str(self.chat.id), user=self.a)
        self.reveal.submit_intent(chat_id=str(self.chat.id), user=self.b)

    def _verify(self, user, token, purpose=PaymentPurpose.REVEAL, product_id="reveal_unlock"):
        return self.service.verify_google_play_purchase(
            user=user,
            chat_id=str(self.chat.id),
            purpose=purpose,
            product_id=product_id,
            purchase_token=token,
            initiated_from=PaymentInitiatedFrom.CHAT_SCREEN,
        )

    def test_mutual_reveal_purchase_reveals_chat(self) -> None:
        self._mutual()
        with mock.patch(_VERIFY_PLAY, side_effect=_purchase_stub):
            self._verify(self.a, "tok_a")
            self.chat.refresh_from_db()
            self.assertEqual(self.chat.status, ChatStatus.ACTIVE)  # not until both pay
            self._verify(self.b, "tok_b")
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, ChatStatus.REVEALED)

        payment = Payment.objects.get(user=self.a, chat=self.chat)
        self.assertEqual(payment.provider, PaymentProvider.GOOGLE_PLAY)
        self.assertEqual(payment.provider_payment_id, "tok_a")
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(payment.metadata.get("product_id"), "reveal_unlock")

    def test_purchase_is_idempotent_on_token(self) -> None:
        self._mutual()
        with mock.patch(_VERIFY_PLAY, side_effect=_purchase_stub):
            first = self._verify(self.a, "tok_same")
            second = self._verify(self.a, "tok_same")
        self.assertTrue(first.success and second.success)
        self.assertEqual(first.data.id, second.data.id)
        self.assertEqual(Payment.objects.filter(user=self.a).count(), 1)

    def test_product_purpose_mismatch_rejected(self) -> None:
        self._mutual()
        result = self._verify(self.a, "tok", product_id="chat_extension")
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_invalid_purchase_rejected(self) -> None:
        self._mutual()
        with mock.patch(_VERIFY_PLAY, side_effect=InvalidPurchase()):
            result = self._verify(self.a, "tok")
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_reveal_requires_mutual_intent(self) -> None:
        with mock.patch(_VERIFY_PLAY, side_effect=_purchase_stub):
            result = self._verify(self.a, "tok")
        self.assertEqual(result.error_code, "VALIDATION_ERROR")
