"""API tests for the payments endpoints (Razorpay gateway mocked)."""

from __future__ import annotations

import json
import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.payments.enums import PaymentPurpose, PaymentStatus
from apps.payments.gateway import InvalidPaymentSignature
from apps.payments.models import Payment
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


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _order_stub(**_kwargs):
    return {"id": "order_" + uuid.uuid4().hex}


class PaymentApiTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.a = _user()
        self.b = _user()
        self.chat = ChatService().create_chat(self.a, self.b).data
        Chat.objects.filter(id=self.chat.id).update(message_count=100)
        self.reveal = RevealService()

    def _make_mutual(self) -> None:
        self.reveal.submit_intent(chat_id=str(self.chat.id), user=self.a)
        self.reveal.submit_intent(chat_id=str(self.chat.id), user=self.b)

    def _create_order(self, user):
        return _client(user).post(
            "/api/v1/payments/create-order",
            {
                "chat_id": str(self.chat.id),
                "purpose": PaymentPurpose.REVEAL,
                "initiated_from": "CHAT_SCREEN",
            },
            format="json",
        )

    def test_create_order_requires_mutual_intent(self) -> None:
        with mock.patch(_ORDER, side_effect=_order_stub):
            response = self._create_order(self.a)
        self.assertEqual(response.status_code, 400)

    def test_create_order_success(self) -> None:
        self._make_mutual()
        with mock.patch(_ORDER, side_effect=_order_stub):
            response = self._create_order(self.a)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["data"]["order_id"].startswith("order_"))

    def test_verify_marks_success(self) -> None:
        self._make_mutual()
        with mock.patch(_ORDER, side_effect=_order_stub):
            order = self._create_order(self.a).json()["data"]
        with mock.patch(_VERIFY, return_value=None):
            response = _client(self.a).post(
                "/api/v1/payments/verify",
                {
                    "razorpay_order_id": order["order_id"],
                    "razorpay_payment_id": "pay_a",
                    "razorpay_signature": "sig",
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], PaymentStatus.SUCCESS)

    def test_webhook_valid_signature(self) -> None:
        self._make_mutual()
        with mock.patch(_ORDER, side_effect=_order_stub):
            order = self._create_order(self.a).json()["data"]
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
            response = APIClient().post(
                "/api/v1/payments/webhook",
                data=body,
                content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE="sig",
            )
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get(provider_order_id=order["order_id"])
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)

    def test_webhook_invalid_signature(self) -> None:
        with mock.patch(_WEBHOOK, side_effect=InvalidPaymentSignature()):
            response = APIClient().post(
                "/api/v1/payments/webhook",
                data="{}",
                content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE="bad",
            )
        self.assertEqual(response.status_code, 401)

    def test_payment_detail_ownership(self) -> None:
        self._make_mutual()
        with mock.patch(_ORDER, side_effect=_order_stub):
            order = self._create_order(self.a).json()["data"]
        payment_id = order["payment_id"]
        own = _client(self.a).get(f"/api/v1/payments/{payment_id}")
        self.assertEqual(own.status_code, 200)
        other = _client(self.b).get(f"/api/v1/payments/{payment_id}")
        self.assertEqual(other.status_code, 404)

    def test_chat_payment_status(self) -> None:
        response = _client(self.a).get(f"/api/v1/chats/{self.chat.id}/payments/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("reveal", response.json()["data"])
