"""PaymentService tests: orders, webhook, bundles, and coin spend (new model)."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.payments.enums import PaymentInitiatedFrom, PaymentPurpose, PaymentStatus
from apps.payments.models import Payment
from apps.payments.services.credit_service import CreditService
from apps.payments.services.payment_service import PaymentService
from apps.reveal.enums import DecisionChoice
from apps.reveal.services.reveal_service import RevealService
from apps.users.enums import Gender
from apps.users.models import User

_WEBHOOK = "apps.payments.gateway.verify_webhook_signature"
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
            chat_service=self.chats,
            reveal_service=self.reveal,
            credit_service=self.credits,
            notification_service=notif,
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

    def _order(self, user, purpose=PaymentPurpose.REVEAL):
        return self.service.create_order(
            user=user,
            chat_id=str(self.chat.id),
            purpose=purpose,
            initiated_from=PaymentInitiatedFrom.CHAT_SCREEN,
        )

    # -- order context ------------------------------------------------------

    def test_create_order_requires_active_payment_round(self) -> None:
        result = self._order(self.boy)  # no decision made yet
        self.assertEqual(result.error_code, "CONFLICT")

    def test_create_order_in_payment_phase(self) -> None:
        self._reach_reveal_payment()
        result = self._order(self.boy)
        self.assertTrue(result.success)
        self.assertTrue(result.data["dev_bypass"])
        self.assertTrue(result.data["order_id"].startswith("dev_order_"))

    def test_create_order_is_idempotent(self) -> None:
        self._reach_reveal_payment()
        first = self._order(self.boy)
        second = self._order(self.boy)
        self.assertEqual(first.data["order_id"], second.data["order_id"])
        self.assertEqual(Payment.objects.filter(user=self.boy).count(), 1)

    def test_double_pay_same_side_rejected(self) -> None:
        self._reach_reveal_payment()
        order = self._order(self.boy).data
        self.service.verify_payment(
            order_id=order["order_id"], payment_id="dev", signature="dev"
        )
        # Second order for the same already-paid side is rejected.
        self.assertEqual(self._order(self.boy).error_code, "CONFLICT")

    # -- webhook ------------------------------------------------------------

    def test_webhook_marks_success(self) -> None:
        self._reach_reveal_payment()
        order = self._order(self.boy).data
        body = json.dumps(
            {
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {"id": "pay_x", "order_id": order["order_id"]}
                    }
                },
            }
        )
        with mock.patch(_WEBHOOK, return_value=None):
            result = self.service.process_webhook(body=body, signature="sig")
        self.assertTrue(result.success)
        payment = Payment.objects.get(provider_order_id=order["order_id"])
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)

    # -- store bundle -> coins ---------------------------------------------

    def test_purchase_bundle_grants_coins(self) -> None:
        with mock.patch(_VERIFY_PLAY, side_effect=_play_stub):
            result = self.service.purchase_bundle(
                user=self.boy,
                product_id="standard_reveal_3",
                purchase_token="tok_" + uuid.uuid4().hex,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.data["coins_added"], 3)
        self.assertEqual(self.credits.get_balances(self.boy)["reveal_coins"], 3)

    def test_purchase_bundle_idempotent_on_token(self) -> None:
        token = "tok_" + uuid.uuid4().hex
        with mock.patch(_VERIFY_PLAY, side_effect=_play_stub):
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
