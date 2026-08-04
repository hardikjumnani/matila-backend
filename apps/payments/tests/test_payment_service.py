"""Tests for PaymentService (Razorpay gateway mocked)."""

from __future__ import annotations

import json
import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.chats.enums import ChatStatus
from apps.chats.services.chat_service import ChatService
from apps.payments.enums import PaymentInitiatedFrom, PaymentPurpose, PaymentStatus
from apps.payments.gateway import InvalidPaymentSignature
from apps.payments.models import Payment
from apps.payments.services.payment_service import PaymentService
from apps.reveal.services.reveal_service import RevealService
from apps.users.models import User

_ORDER = "apps.payments.gateway.create_order"
_VERIFY = "apps.payments.gateway.verify_payment_signature"
_WEBHOOK = "apps.payments.gateway.verify_webhook_signature"


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


def _order_stub(**_kwargs):
    return {"id": "order_" + uuid.uuid4().hex}


class PaymentServiceTests(TestCase):
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

    def _mutual_reveal(self) -> None:
        self.reveal.submit_intent(chat_id=str(self.chat.id), user=self.a)
        self.reveal.submit_intent(chat_id=str(self.chat.id), user=self.b)

    def _create_order(self, user, purpose):
        return self.service.create_order(
            user=user,
            chat_id=str(self.chat.id),
            purpose=purpose,
            initiated_from=PaymentInitiatedFrom.CHAT_SCREEN,
        )

    # -- Order creation -----------------------------------------------------

    def test_reveal_order_requires_mutual_intent(self) -> None:
        with mock.patch(_ORDER, side_effect=_order_stub):
            result = self._create_order(self.a, PaymentPurpose.REVEAL)
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_create_reveal_order(self) -> None:
        self._mutual_reveal()
        with mock.patch(_ORDER, side_effect=_order_stub):
            result = self._create_order(self.a, PaymentPurpose.REVEAL)
        self.assertTrue(result.success)
        self.assertTrue(result.data["order_id"].startswith("order_"))
        self.assertEqual(Payment.objects.filter(chat=self.chat).count(), 1)

    def test_create_order_is_idempotent(self) -> None:
        self._mutual_reveal()
        with mock.patch(_ORDER, side_effect=_order_stub):
            first = self._create_order(self.a, PaymentPurpose.REVEAL)
            second = self._create_order(self.a, PaymentPurpose.REVEAL)
        self.assertEqual(first.data["order_id"], second.data["order_id"])
        self.assertEqual(Payment.objects.filter(user=self.a).count(), 1)

    # -- Verification -------------------------------------------------------

    def test_invalid_signature_rejected(self) -> None:
        self._mutual_reveal()
        with mock.patch(_ORDER, side_effect=_order_stub):
            order = self._create_order(self.a, PaymentPurpose.REVEAL).data
        with mock.patch(_VERIFY, side_effect=InvalidPaymentSignature()):
            result = self.service.verify_payment(
                order_id=order["order_id"], payment_id="pay_x", signature="bad"
            )
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_mutual_reveal_payment_reveals_chat(self) -> None:
        self._mutual_reveal()
        with mock.patch(_ORDER, side_effect=_order_stub):
            order_a = self._create_order(self.a, PaymentPurpose.REVEAL).data
            order_b = self._create_order(self.b, PaymentPurpose.REVEAL).data

        with mock.patch(_VERIFY, return_value=None):
            self.service.verify_payment(
                order_id=order_a["order_id"], payment_id="pay_a", signature="s"
            )
            # Not revealed until both pay.
            self.chat.refresh_from_db()
            self.assertEqual(self.chat.status, ChatStatus.ACTIVE)
            self.service.verify_payment(
                order_id=order_b["order_id"], payment_id="pay_b", signature="s"
            )
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, ChatStatus.REVEALED)

    def test_verify_is_idempotent(self) -> None:
        self._mutual_reveal()
        with mock.patch(_ORDER, side_effect=_order_stub):
            order = self._create_order(self.a, PaymentPurpose.REVEAL).data
        with mock.patch(_VERIFY, return_value=None):
            self.service.verify_payment(
                order_id=order["order_id"], payment_id="pay_a", signature="s"
            )
            self.service.verify_payment(
                order_id=order["order_id"], payment_id="pay_a", signature="s"
            )
        payment = Payment.objects.get(provider_order_id=order["order_id"])
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)

    def test_create_order_blocks_double_pay(self) -> None:
        self._mutual_reveal()
        with mock.patch(_ORDER, side_effect=_order_stub):
            order = self._create_order(self.a, PaymentPurpose.REVEAL).data
        with mock.patch(_VERIFY, return_value=None):
            self.service.verify_payment(
                order_id=order["order_id"], payment_id="pay_a", signature="s"
            )
        # A second order for the same user+chat+purpose after success is rejected.
        with mock.patch(_ORDER, side_effect=_order_stub):
            result = self._create_order(self.a, PaymentPurpose.REVEAL)
        self.assertEqual(result.error_code, "CONFLICT")

    # -- Extension ----------------------------------------------------------

    def test_both_extension_payments_extend_chat(self) -> None:
        self.chats.expire_chat(str(self.chat.id))
        with mock.patch(_ORDER, side_effect=_order_stub):
            order_a = self._create_order(self.a, PaymentPurpose.CHAT_EXTENSION).data
            order_b = self._create_order(self.b, PaymentPurpose.CHAT_EXTENSION).data
        with mock.patch(_VERIFY, return_value=None):
            self.service.verify_payment(
                order_id=order_a["order_id"], payment_id="pay_a", signature="s"
            )
            self.chat.refresh_from_db()
            self.assertEqual(self.chat.status, ChatStatus.EXPIRED)
            self.service.verify_payment(
                order_id=order_b["order_id"], payment_id="pay_b", signature="s"
            )
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, ChatStatus.EXTENDED)

    def test_extension_order_requires_expired_chat(self) -> None:
        with mock.patch(_ORDER, side_effect=_order_stub):
            result = self._create_order(self.a, PaymentPurpose.CHAT_EXTENSION)
        self.assertEqual(result.error_code, "CONFLICT")

    # -- Webhook ------------------------------------------------------------

    def test_webhook_marks_payment_success(self) -> None:
        self._mutual_reveal()
        with mock.patch(_ORDER, side_effect=_order_stub):
            order = self._create_order(self.a, PaymentPurpose.REVEAL).data
        body = json.dumps(
            {
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {"id": "pay_hook", "order_id": order["order_id"]}
                    }
                },
            }
        )
        with mock.patch(_WEBHOOK, return_value=None):
            result = self.service.process_webhook(body=body, signature="sig")
        self.assertTrue(result.success)
        payment = Payment.objects.get(provider_order_id=order["order_id"])
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)

    def test_webhook_invalid_signature_rejected(self) -> None:
        with mock.patch(_WEBHOOK, side_effect=InvalidPaymentSignature()):
            result = self.service.process_webhook(body="{}", signature="bad")
        self.assertEqual(result.error_code, "UNAUTHORIZED")

    # -- Dev bypass ---------------------------------------------------------

    def test_order_payload_flags_dev_bypass_false_by_default(self) -> None:
        self._mutual_reveal()
        with mock.patch(_ORDER, side_effect=_order_stub):
            result = self._create_order(self.a, PaymentPurpose.REVEAL)
        self.assertFalse(result.data["dev_bypass"])

    @override_settings(PAYMENTS_DEV_BYPASS=True)
    def test_dev_bypass_create_order_skips_gateway(self) -> None:
        self._mutual_reveal()
        with mock.patch(_ORDER) as order_mock:
            result = self._create_order(self.a, PaymentPurpose.REVEAL)
        order_mock.assert_not_called()
        self.assertTrue(result.success)
        self.assertTrue(result.data["dev_bypass"])
        self.assertTrue(result.data["order_id"].startswith("dev_order_"))

    @override_settings(PAYMENTS_DEV_BYPASS=True)
    def test_dev_bypass_reveal_completes_without_signature(self) -> None:
        self._mutual_reveal()
        order_a = self._create_order(self.a, PaymentPurpose.REVEAL).data
        order_b = self._create_order(self.b, PaymentPurpose.REVEAL).data
        with mock.patch(_VERIFY) as verify_mock:
            self.service.verify_payment(
                order_id=order_a["order_id"],
                payment_id="dev_bypass",
                signature="dev_bypass",
            )
            self.service.verify_payment(
                order_id=order_b["order_id"],
                payment_id="dev_bypass",
                signature="dev_bypass",
            )
        verify_mock.assert_not_called()
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, ChatStatus.REVEALED)
