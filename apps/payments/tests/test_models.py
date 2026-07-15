"""Model tests for the payments domain."""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.chats.models import Chat
from apps.payments.enums import PaymentInitiatedFrom, PaymentPurpose, PaymentStatus
from apps.payments.models import Payment
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class PaymentModelTests(TestCase):
    def _payment(self, **overrides) -> Payment:
        data = {
            "user": _user(),
            "chat": Chat.objects.create(),
            "purpose": PaymentPurpose.REVEAL,
            "amount_in_paise": 5900,
            "initiated_from": PaymentInitiatedFrom.CHAT_SCREEN,
        }
        data.update(overrides)
        return Payment.objects.create(**data)

    def test_defaults(self) -> None:
        payment = self._payment()
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertEqual(payment.currency, "INR")

    def test_multiple_pending_payments_without_provider_ids_are_allowed(self) -> None:
        """NULL provider ids must not collide (many pending orders can coexist)."""
        self._payment()
        self._payment()  # Must not raise despite both having NULL provider ids.
        self.assertEqual(Payment.objects.count(), 2)

    def test_provider_payment_id_is_unique(self) -> None:
        self._payment(provider_payment_id="pay_123")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._payment(provider_payment_id="pay_123")
