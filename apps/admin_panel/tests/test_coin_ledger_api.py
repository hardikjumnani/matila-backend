"""Admin API tests for the per-user coin ledger tab."""

from __future__ import annotations

import uuid

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.payments.enums import (
    CoinLedgerReason,
    PaymentPurpose,
    PaymentStatus,
)
from apps.payments.models import Payment
from apps.payments.services.credit_service import CreditService
from apps.users.models import User

_ADMIN_EMAIL = "coinadmin@college.edu"


def _user(email=None, name="Test User") -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=email or f"{uuid.uuid4().hex}@college.edu",
        full_name=name,
    )


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminCoinLedgerApiTests(TestCase):
    def setUp(self) -> None:
        self.admin = _user(_ADMIN_EMAIL, name="Admin")
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.target = _user(name="Rahul Verma")
        credits = CreditService()
        # Bought a 10-pack (Rs 59) -> +10 coins, linked to the Payment.
        self.payment = Payment.objects.create(
            user=self.target,
            purpose=PaymentPurpose.CREDIT_PURCHASE,
            amount_in_paise=5900,
            status=PaymentStatus.SUCCESS,
            metadata={"product_id": "coin_pack_10", "coins": 10},
        )
        credits.credit(
            user=self.target, amount=10,
            reason=CoinLedgerReason.BUNDLE_PURCHASE,
            idempotency_key="bundle:tok1", payment=self.payment,
        )
        # Spent 8 on a safe reveal.
        credits.spend(
            user=self.target, amount=8,
            idempotency_key="consume:r1:u1",
            reason=CoinLedgerReason.ACTION_CONSUME, purpose="SAFE_REVEAL",
        )

    def test_overview(self):
        resp = self.client.get(f"/api/v1/admin/users/{self.target.id}/coins")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["wallet"]["coins"], 2)
        self.assertEqual(data["totals"]["purchased_coins"], 10)
        self.assertEqual(data["totals"]["spent_coins"], 8)
        self.assertEqual(data["totals"]["lifetime_rupees_paise"], 5900)
        self.assertEqual(len(data["recent_ledger"]), 2)

    def test_ledger_list_labels_and_provenance(self):
        resp = self.client.get(f"/api/v1/admin/users/{self.target.id}/coin-ledger")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["data"]["items"]
        self.assertEqual(len(items), 2)
        spend = next(i for i in items if i["direction"] == "spend")
        self.assertEqual(spend["purpose"], "SAFE_REVEAL")
        self.assertIn("safe reveal", spend["label"])
        self.assertEqual(spend["balance_after"], 2)
        buy = next(i for i in items if i["direction"] == "credit")
        self.assertEqual(buy["balance_after"], 10)
        self.assertEqual(buy["payment"]["amount_in_paise"], 5900)
        self.assertEqual(buy["payment"]["coins"], 10)
        self.assertIn("Bought 10 coins", buy["label"])

    def test_never_transacted_user_is_zeroed_not_404(self):
        fresh = _user()
        resp = self.client.get(f"/api/v1/admin/users/{fresh.id}/coins")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["wallet"]["coins"], 0)
        self.assertEqual(data["recent_ledger"], [])

    def test_unknown_user_404(self):
        resp = self.client.get(f"/api/v1/admin/users/{uuid.uuid4()}/coins")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "RESOURCE_NOT_FOUND")

    def test_user_search_by_id_and_firebase_uid(self):
        by_id = self.client.get(f"/api/v1/admin/users?q={self.target.id}")
        self.assertTrue(
            any(i["id"] == str(self.target.id) for i in by_id.json()["data"]["items"])
        )
        by_uid = self.client.get(f"/api/v1/admin/users?q={self.target.firebase_uid}")
        self.assertTrue(
            any(i["id"] == str(self.target.id) for i in by_uid.json()["data"]["items"])
        )

    def test_non_admin_denied(self):
        client = APIClient()
        client.force_authenticate(user=_user())
        self.assertEqual(
            client.get(f"/api/v1/admin/users/{self.target.id}/coins").status_code, 403
        )
