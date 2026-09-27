"""API tests for the payments / store / wallet endpoints (new model)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
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


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _play_stub(**_kwargs):
    return {"purchaseState": 0, "orderId": "GPA." + uuid.uuid4().hex}


class PaymentApiTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.boy = _user(Gender.MALE)
        self.girl = _user(Gender.FEMALE)
        self.chat = ChatService().create_chat(self.boy, self.girl).data
        Chat.objects.filter(id=self.chat.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )
        self.reveal = RevealService()

    def test_store_catalog(self) -> None:
        resp = _client(self.boy).get("/api/v1/store/catalog")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(len(data["standard_reveal_bundles"]), 4)
        self.assertEqual(data["safe_reveal"]["female_price_paise"], 6900)

    def test_wallet_starts_empty(self) -> None:
        resp = _client(self.boy).get("/api/v1/wallet")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["reveal_coins"], 0)

    def test_store_purchase_grants_coins(self) -> None:
        with mock.patch(_VERIFY_PLAY, side_effect=_play_stub):
            resp = _client(self.boy).post(
                "/api/v1/store/purchase",
                {"product_id": "standard_reveal_5", "purchase_token": "tok1"},
                format="json",
            )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["data"]["coins_added"], 5)
        wallet = _client(self.boy).get("/api/v1/wallet").json()
        self.assertEqual(wallet["data"]["reveal_coins"], 5)

    @override_settings(PAYMENTS_DEV_BYPASS=True)
    def test_create_order_in_payment_phase(self) -> None:
        self.reveal.submit_decision(
            chat_id=str(self.chat.id), user=self.boy, choice=DecisionChoice.REVEAL
        )
        self.reveal.submit_decision(
            chat_id=str(self.chat.id), user=self.girl, choice=DecisionChoice.REVEAL
        )
        resp = _client(self.boy).post(
            "/api/v1/payments/create-order",
            {
                "chat_id": str(self.chat.id),
                "purpose": "REVEAL",
                "initiated_from": "CHAT_SCREEN",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.json()["data"]["dev_bypass"])

    def test_pay_with_coin_endpoint(self) -> None:
        from apps.payments.services.credit_service import CreditService

        CreditService().credit(
            user=self.boy, coin_type="REVEAL", amount=1,
            reason="ADMIN_ADJUST", idempotency_key="seed",
        )
        self.reveal.submit_decision(
            chat_id=str(self.chat.id), user=self.boy, choice=DecisionChoice.REVEAL
        )
        self.reveal.submit_decision(
            chat_id=str(self.chat.id), user=self.girl, choice=DecisionChoice.REVEAL
        )
        resp = _client(self.boy).post(
            "/api/v1/payments/pay-with-coin",
            {"chat_id": str(self.chat.id), "purpose": "REVEAL"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["balances"]["reveal_coins"], 0)
