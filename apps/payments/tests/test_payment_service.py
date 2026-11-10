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
from apps.configuration.constants import FeatureFlagKey
from apps.configuration.models import FeatureFlag
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
        # Some tests here drive the direct cash-per-action path, which is gated
        # behind DIRECT_ACTION_PURCHASE_ENABLED (off by default). Turn it on.
        FeatureFlag.objects.create(
            key=FeatureFlagKey.DIRECT_ACTION_PURCHASE_ENABLED, value=True
        )
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
        self.assertEqual(result.data.amount_in_paise, 5000)
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
            user=self.boy, product_id="coins_30",
            purchase_token="tok_" + uuid.uuid4().hex,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["coins_added"], 30)
        self.assertEqual(self.credits.get_balances(self.boy)["coins"], 30)

    def test_purchase_bundle_idempotent_on_token(self) -> None:
        token = "tok_" + uuid.uuid4().hex
        self.service.purchase_bundle(
            user=self.boy, product_id="coins_50", purchase_token=token
        )
        self.service.purchase_bundle(
            user=self.boy, product_id="coins_50", purchase_token=token
        )
        self.assertEqual(self.credits.get_balances(self.boy)["coins"], 50)

    def test_purchase_unknown_product_rejected(self) -> None:
        result = self.service.purchase_bundle(
            user=self.boy, product_id="not_a_product", purchase_token="t"
        )
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    # -- pay with coin ------------------------------------------------------

    def test_pay_with_coin_spends_balance(self) -> None:
        # Reveal costs 10 coins; seed exactly that and expect a zero balance after.
        self.credits.credit(
            user=self.boy, amount=10, reason="ADMIN_ADJUST", idempotency_key="seed",
        )
        # Regular (non-first) reveal here; the first-reveal discount path is
        # covered in FirstRevealDiscountTests.
        self.boy.has_completed_reveal = True
        self.boy.save(update_fields=["has_completed_reveal"])
        self._reach_reveal_payment()
        result = self.service.pay_with_coin(
            user=self.boy, chat_id=str(self.chat.id), purpose=PaymentPurpose.REVEAL
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["balances"]["coins"], 0)
        self.assertTrue(self.reveal.has_paid(self.chat, self.boy))

    def test_pay_with_coin_requires_active_round(self) -> None:
        self.credits.credit(
            user=self.boy, amount=10, reason="ADMIN_ADJUST", idempotency_key="seed",
        )
        result = self.service.pay_with_coin(
            user=self.boy, chat_id=str(self.chat.id), purpose=PaymentPurpose.REVEAL
        )
        self.assertEqual(result.error_code, "NO_ACTIVE_PAYMENT")

    # -- has_held_coins flag ------------------------------------------------

    def test_has_held_coins_false_until_first_credit(self) -> None:
        self.assertFalse(self.credits.get_balances(self.boy)["has_held_coins"])
        self.credits.credit(
            user=self.boy, amount=10, reason="ADMIN_ADJUST", idempotency_key="k1",
        )
        self.assertTrue(self.credits.get_balances(self.boy)["has_held_coins"])

    def test_has_held_coins_sticky_after_drain(self) -> None:
        self.credits.credit(
            user=self.boy, amount=10, reason="ADMIN_ADJUST", idempotency_key="k2",
        )
        self.credits.spend(user=self.boy, amount=10, idempotency_key="s1")
        bal = self.credits.get_balances(self.boy)
        self.assertEqual(bal["coins"], 0)
        self.assertTrue(bal["has_held_coins"])  # stays true after returning to 0


@override_settings(PAYMENTS_DEV_BYPASS=True)
class FirstRevealDiscountTests(TestCase):
    """One-time first-reveal discount: a user's first full reveal costs 8 coins,
    every later reveal costs the regular 10. See FIRST_REVEAL_DISCOUNT_PLAN.md."""

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
        for u in (self.boy, self.girl):
            self.credits.credit(
                user=u, amount=100, reason="ADMIN_ADJUST", idempotency_key=f"seed-{u.id}",
            )

    def _fresh_chat(self, a, b):
        chat = self.chats.create_chat(a, b).data
        Chat.objects.filter(id=chat.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )
        return chat

    def _reach_payment(self, chat, a, b):
        self.reveal.submit_decision(
            chat_id=str(chat.id), user=a, choice=DecisionChoice.REVEAL
        )
        self.reveal.submit_decision(
            chat_id=str(chat.id), user=b, choice=DecisionChoice.REVEAL
        )

    def _coins(self, u):
        return self.credits.get_balances(u)["coins"]

    def test_first_reveal_is_8_then_regular_10(self) -> None:
        # First reveal: boy charged 8 (discount).
        chat1 = self._fresh_chat(self.boy, self.girl)
        self._reach_payment(chat1, self.boy, self.girl)
        before = self._coins(self.boy)
        self.service.pay_with_coin(
            user=self.boy, chat_id=str(chat1.id), purpose=PaymentPurpose.REVEAL
        )
        self.assertEqual(before - self._coins(self.boy), 8)
        # Complete the reveal (girl pays) -> both flagged as having revealed.
        self.service.pay_with_coin(
            user=self.girl, chat_id=str(chat1.id), purpose=PaymentPurpose.REVEAL
        )
        self.boy.refresh_from_db()
        self.assertTrue(self.boy.has_completed_reveal)

        # Second reveal (new partner): boy now charged the regular 10.
        girl2 = _user(Gender.FEMALE)
        self.credits.credit(
            user=girl2, amount=100, reason="ADMIN_ADJUST", idempotency_key="seed-g2",
        )
        self.boy.refresh_from_db()
        chat2 = self._fresh_chat(self.boy, girl2)
        self._reach_payment(chat2, self.boy, girl2)
        before2 = self._coins(self.boy)
        self.service.pay_with_coin(
            user=self.boy, chat_id=str(chat2.id), purpose=PaymentPurpose.REVEAL
        )
        self.assertEqual(before2 - self._coins(self.boy), 10)

    def test_discount_flag_off_charges_regular(self) -> None:
        FeatureFlag.objects.create(
            key=FeatureFlagKey.FIRST_REVEAL_DISCOUNT_ENABLED, value=False
        )
        cache.clear()
        chat = self._fresh_chat(self.boy, self.girl)
        self._reach_payment(chat, self.boy, self.girl)
        before = self._coins(self.boy)
        self.service.pay_with_coin(
            user=self.boy, chat_id=str(chat.id), purpose=PaymentPurpose.REVEAL
        )
        self.assertEqual(before - self._coins(self.boy), 10)  # no discount

    def test_refund_matches_first_reveal_charge_and_keeps_discount(self) -> None:
        from apps.reveal.models import DecisionRound

        chat = self._fresh_chat(self.boy, self.girl)
        self._reach_payment(chat, self.boy, self.girl)
        self.service.pay_with_coin(
            user=self.boy, chat_id=str(chat.id), purpose=PaymentPurpose.REVEAL
        )
        before = self._coins(self.boy)  # boy charged 8, girl not yet paid
        round_ = DecisionRound.objects.get(id=self.reveal.active_round_id(chat))
        self.reveal._credit_unmatched_payments(round_)
        self.assertEqual(self._coins(self.boy) - before, 8)  # refunded exactly 8
        self.boy.refresh_from_db()
        self.assertFalse(self.boy.has_completed_reveal)  # discount preserved

    def test_state_payload_exposes_user_aware_price(self) -> None:
        chat = self._fresh_chat(self.boy, self.girl)
        st = self.reveal.get_decision_state(chat_id=str(chat.id), user=self.boy).data
        self.assertEqual(st["coin_cost_reveal"], 8)
        self.assertTrue(st["first_reveal"])
        self.boy.has_completed_reveal = True
        self.boy.save(update_fields=["has_completed_reveal"])
        st2 = self.reveal.get_decision_state(chat_id=str(chat.id), user=self.boy).data
        self.assertEqual(st2["coin_cost_reveal"], 10)
        self.assertFalse(st2["first_reveal"])
