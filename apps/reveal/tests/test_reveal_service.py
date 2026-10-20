"""
Decision-round state-machine tests (the reveal/safe/extend/exit matrix).

Payments are driven through the real prod paths: standard reveal via pay-with-coin,
safe reveal / extension via Google Play verify (dev-bypass skips the Play API call).
Both route success into RevealService.record_payment. See docs/REVEAL_FLOW_SPEC.md.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.chats.enums import ChatStatus, EndReason
from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.payments.enums import PaymentInitiatedFrom, PaymentPurpose
from apps.payments.services.credit_service import CreditService
from apps.payments.services.payment_service import PaymentService
from apps.reveal.enums import (
    DecisionChoice,
    DecisionRoundPhase,
    FinalCall,
    SafeRevealDecision,
)
from apps.reveal.models import DecisionRound
from apps.reveal.services.reveal_service import RevealService
from apps.users.enums import Gender
from apps.users.models import User


def _user(gender: str) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        full_name=f"{gender.title()} User",
        gender=gender,
        intent="RELATIONSHIP",
        gender_preferences=[Gender.MALE, Gender.FEMALE],
    )


@override_settings(PAYMENTS_DEV_BYPASS=True)
class DecisionFlowTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        notif = mock.MagicMock()
        self.chats = ChatService(notification_service=notif)
        self.reveal = RevealService(chat_service=self.chats, notification_service=notif)
        self.credits = CreditService()
        self.pay = PaymentService(
            chat_service=self.chats,
            reveal_service=self.reveal,
            credit_service=self.credits,
            notification_service=notif,
        )
        self.boy = _user(Gender.MALE)
        self.girl = _user(Gender.FEMALE)
        self.chat = self.chats.create_chat(self.boy, self.girl).data

    # -- helpers ------------------------------------------------------------

    def _refresh(self) -> Chat:
        self.chat.refresh_from_db()
        return self.chat

    def _make_eligible(self) -> None:
        Chat.objects.filter(id=self.chat.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )

    def _decide(self, user, choice):
        return self.reveal.submit_decision(
            chat_id=str(self.chat.id), user=user, choice=choice
        )

    def _pay(self, user, purpose):
        """Pay one side the prod way: coins for REVEAL, Play verify for the rest."""
        if purpose == PaymentPurpose.REVEAL:
            self.credits.credit(
                user=user, amount=10,
                reason="ADMIN_ADJUST", idempotency_key=f"seed:{user.id}:{uuid.uuid4().hex}",
            )
            return self.pay.pay_with_coin(
                user=user, chat_id=str(self.chat.id), purpose=PaymentPurpose.REVEAL
            )
        if purpose == PaymentPurpose.SAFE_REVEAL:
            sku = "safe_reveal_female" if user.gender == Gender.FEMALE else "safe_reveal_male"
            return self.pay.verify_google_play_purchase(
                user=user, chat_id=str(self.chat.id), purpose=PaymentPurpose.SAFE_REVEAL,
                product_id=sku, purchase_token=f"tok_{uuid.uuid4().hex}",
                initiated_from=PaymentInitiatedFrom.CHAT_SCREEN,
            )
        return self.pay.verify_google_play_purchase(
            user=user, chat_id=str(self.chat.id), purpose=PaymentPurpose.CHAT_EXTENSION,
            product_id="chat_extension", purchase_token=f"tok_{uuid.uuid4().hex}",
            initiated_from=PaymentInitiatedFrom.CHAT_EXPIRED,
        )

    def _round(self) -> DecisionRound:
        return DecisionRound.objects.filter(chat=self.chat).latest("created_at")

    # -- eligibility --------------------------------------------------------

    def test_not_eligible_before_time_or_messages(self) -> None:
        self.assertFalse(self.reveal.is_eligible(self._refresh()))
        # Reveal not offered mid-chat while ineligible; exit is.
        choices = self.reveal.available_choices(self.chat, self.boy)
        self.assertNotIn(DecisionChoice.REVEAL, choices)
        self.assertIn(DecisionChoice.EXIT, choices)

    def test_eligible_by_time(self) -> None:
        self._make_eligible()
        self.assertTrue(self.reveal.is_eligible(self._refresh()))

    def test_eligible_by_messages_each(self) -> None:
        from apps.messaging.models import Message

        for _ in range(5):
            Message.objects.create(chat=self.chat, sender=self.boy, text_content="hi")
            Message.objects.create(chat=self.chat, sender=self.girl, text_content="yo")
        self.assertTrue(self.reveal.is_eligible(self._refresh()))

    def test_not_eligible_when_one_user_under_five(self) -> None:
        from apps.messaging.models import Message

        for _ in range(5):
            Message.objects.create(chat=self.chat, sender=self.boy, text_content="hi")
        for _ in range(4):
            Message.objects.create(chat=self.chat, sender=self.girl, text_content="yo")
        self.assertFalse(self.reveal.is_eligible(self._refresh()))

    # -- available choices / role ------------------------------------------

    def test_safe_reveal_only_for_female_in_bg(self) -> None:
        self._make_eligible()
        self.assertIn(
            DecisionChoice.SAFE_REVEAL,
            self.reveal.available_choices(self._refresh(), self.girl),
        )
        self.assertNotIn(
            DecisionChoice.SAFE_REVEAL,
            self.reveal.available_choices(self.chat, self.boy),
        )

    def test_no_safe_reveal_in_male_male(self) -> None:
        m1 = _user(Gender.MALE)
        m2 = _user(Gender.MALE)
        chat = self.chats.create_chat(m1, m2).data
        Chat.objects.filter(id=chat.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )
        chat.refresh_from_db()
        self.assertNotIn(
            DecisionChoice.SAFE_REVEAL,
            self.reveal.available_choices(chat, m2),
        )

    def test_extend_only_after_expiry(self) -> None:
        self._make_eligible()
        self.assertNotIn(
            DecisionChoice.EXTEND, self.reveal.available_choices(self._refresh(), self.boy)
        )
        self.chats.expire_chat(str(self.chat.id))
        self.assertIn(
            DecisionChoice.EXTEND, self.reveal.available_choices(self._refresh(), self.boy)
        )

    # -- finalCall precedence ----------------------------------------------

    def _final_for(self, boy_choice, girl_choice) -> str:
        self.chats.expire_chat(str(self.chat.id))  # expiry → all options available
        self._decide(self.boy, boy_choice)
        self._decide(self.girl, girl_choice)
        return self._round().final_call

    def test_final_both_reveal(self) -> None:
        self.assertEqual(
            self._final_for(DecisionChoice.REVEAL, DecisionChoice.REVEAL),
            FinalCall.REVEAL,
        )

    def test_final_safe_reveal(self) -> None:
        self.assertEqual(
            self._final_for(DecisionChoice.REVEAL, DecisionChoice.SAFE_REVEAL),
            FinalCall.SAFE_REVEAL,
        )

    def test_final_extend_wins_over_reveal(self) -> None:
        self.assertEqual(
            self._final_for(DecisionChoice.EXTEND, DecisionChoice.REVEAL),
            FinalCall.EXTEND,
        )

    def test_final_extend_wins_over_safe(self) -> None:
        self.assertEqual(
            self._final_for(DecisionChoice.EXTEND, DecisionChoice.SAFE_REVEAL),
            FinalCall.EXTEND,
        )

    def test_exit_is_unilateral_and_ends_chat(self) -> None:
        self.chats.expire_chat(str(self.chat.id))
        self._decide(self.boy, DecisionChoice.EXIT)
        self.assertEqual(self._refresh().status, ChatStatus.ENDED)
        self.assertEqual(self.chat.end_reason, EndReason.USER_EXIT)

    # -- standard reveal ----------------------------------------------------

    def test_standard_reveal_both_pay_reveals(self) -> None:
        self._make_eligible()
        self._decide(self.boy, DecisionChoice.REVEAL)
        self._decide(self.girl, DecisionChoice.REVEAL)
        self.assertEqual(self._round().phase, DecisionRoundPhase.PAYMENT)
        self._pay(self.boy, PaymentPurpose.REVEAL)
        self.assertEqual(self._refresh().status, ChatStatus.ACTIVE)  # not until both
        self._pay(self.girl, PaymentPurpose.REVEAL)
        self.assertEqual(self._refresh().status, ChatStatus.REVEALED)

    def test_exit_during_payment_credits_payer_coin(self) -> None:
        self._make_eligible()
        self._decide(self.boy, DecisionChoice.REVEAL)
        self._decide(self.girl, DecisionChoice.REVEAL)
        self._pay(self.boy, PaymentPurpose.REVEAL)
        # Girl exits before paying → boy is refunded the reveal coin cost, chat ends.
        self._decide(self.girl, DecisionChoice.EXIT)
        self.assertEqual(self._refresh().status, ChatStatus.ENDED)
        self.assertEqual(self.credits.get_balances(self.boy)["coins"], 10)
        self.assertEqual(self.credits.get_balances(self.girl)["coins"], 0)

    # -- safe reveal --------------------------------------------------------

    def _reach_safe_decision(self) -> None:
        self._make_eligible()
        self._decide(self.boy, DecisionChoice.REVEAL)
        self._decide(self.girl, DecisionChoice.SAFE_REVEAL)
        self.assertEqual(self._round().final_call, FinalCall.SAFE_REVEAL)
        self._pay(self.boy, PaymentPurpose.SAFE_REVEAL)
        self._pay(self.girl, PaymentPurpose.SAFE_REVEAL)

    def test_safe_reveal_enters_decision_not_revealed(self) -> None:
        self._reach_safe_decision()
        self.assertEqual(self._round().phase, DecisionRoundPhase.SAFE_DECISION)
        self.assertIsNotNone(self._round().boy_revealed_to_girl_at)
        self.assertEqual(self._refresh().status, ChatStatus.ACTIVE)  # not revealed yet

    def test_safe_reveal_boy_visible_only_to_girl(self) -> None:
        self._reach_safe_decision()
        self.assertTrue(self.reveal.safe_reveal_boy_visible_to(self._refresh(), self.girl))
        self.assertFalse(self.reveal.safe_reveal_boy_visible_to(self.chat, self.boy))

    def test_safe_reveal_accept_reveals(self) -> None:
        self._reach_safe_decision()
        result = self.reveal.submit_safe_decision(
            chat_id=str(self.chat.id),
            user=self.girl,
            choice=SafeRevealDecision.REVEAL_YOURSELF,
        )
        self.assertTrue(result.success)
        self.assertEqual(self._refresh().status, ChatStatus.REVEALED)

    def test_safe_reveal_reject_ends_no_coins(self) -> None:
        self._reach_safe_decision()
        self.reveal.submit_safe_decision(
            chat_id=str(self.chat.id), user=self.girl, choice=SafeRevealDecision.EXIT
        )
        self.assertEqual(self._refresh().status, ChatStatus.ENDED)
        self.assertEqual(self.chat.end_reason, EndReason.SAFE_REJECT)
        # No coins for either — the boy was already seen (forfeit).
        self.assertEqual(self.credits.get_balances(self.girl)["coins"], 0)
        self.assertEqual(self.credits.get_balances(self.boy)["coins"], 0)

    def test_boy_cannot_make_safe_decision(self) -> None:
        self._reach_safe_decision()
        result = self.reveal.submit_safe_decision(
            chat_id=str(self.chat.id),
            user=self.boy,
            choice=SafeRevealDecision.REVEAL_YOURSELF,
        )
        self.assertEqual(result.error_code, "FORBIDDEN")

    def test_safe_reveal_exit_before_both_pay_credits_correct_coins(self) -> None:
        self._make_eligible()
        self._decide(self.boy, DecisionChoice.REVEAL)
        self._decide(self.girl, DecisionChoice.SAFE_REVEAL)
        self._pay(self.girl, PaymentPurpose.SAFE_REVEAL)  # girl pays first
        self._decide(self.boy, DecisionChoice.EXIT)  # boy bails
        self.assertEqual(self._refresh().status, ChatStatus.ENDED)
        # Girl is refunded the female safe-reveal coin cost (she paid the safe side).
        self.assertEqual(self.credits.get_balances(self.girl)["coins"], 16)

    # -- extend -------------------------------------------------------------

    def test_extend_both_pay_extends(self) -> None:
        self.chats.expire_chat(str(self.chat.id))
        self._decide(self.boy, DecisionChoice.EXTEND)
        self._decide(self.girl, DecisionChoice.EXTEND)
        self._pay(self.boy, PaymentPurpose.CHAT_EXTENSION)
        self._pay(self.girl, PaymentPurpose.CHAT_EXTENSION)
        chat = self._refresh()
        self.assertEqual(chat.status, ChatStatus.EXTENDED)
        self.assertEqual(chat.anonymous_chat_extension_count, 1)
        self.assertIsNone(chat.decision_deadline_at)

    # -- auto-exit ----------------------------------------------------------

    def test_auto_exit_after_grace_ends_chat(self) -> None:
        self.chats.expire_chat(str(self.chat.id))
        DecisionRound.objects.filter(chat=self.chat).update(
            decision_deadline_at=timezone.now() - timedelta(minutes=1)
        )
        ended = self.reveal.auto_exit_if_stale(self._refresh())
        self.assertTrue(ended)
        self.assertEqual(self._refresh().status, ChatStatus.ENDED)
        self.assertEqual(self.chat.end_reason, EndReason.AUTO_EXIT)

    def test_auto_exit_credits_lone_payer(self) -> None:
        self.chats.expire_chat(str(self.chat.id))
        self._decide(self.boy, DecisionChoice.EXTEND)
        self._decide(self.girl, DecisionChoice.EXTEND)
        self._pay(self.boy, PaymentPurpose.CHAT_EXTENSION)  # only boy pays
        DecisionRound.objects.filter(chat=self.chat).update(
            decision_deadline_at=timezone.now() - timedelta(minutes=1)
        )
        self.reveal.auto_exit_if_stale(self._refresh())
        self.assertEqual(self._refresh().status, ChatStatus.ENDED)
        # Lone extension payer is refunded the extend coin cost.
        self.assertEqual(self.credits.get_balances(self.boy)["coins"], 6)

    # -- coins --------------------------------------------------------------

    def test_pay_with_coin_reveals(self) -> None:
        self.credits.credit(
            user=self.boy, amount=10,
            reason="ADMIN_ADJUST", idempotency_key="seed-boy",
        )
        self.credits.credit(
            user=self.girl, amount=10,
            reason="ADMIN_ADJUST", idempotency_key="seed-girl",
        )
        self._make_eligible()
        self._decide(self.boy, DecisionChoice.REVEAL)
        self._decide(self.girl, DecisionChoice.REVEAL)
        self.pay.pay_with_coin(
            user=self.boy, chat_id=str(self.chat.id), purpose=PaymentPurpose.REVEAL
        )
        self.pay.pay_with_coin(
            user=self.girl, chat_id=str(self.chat.id), purpose=PaymentPurpose.REVEAL
        )
        self.assertEqual(self._refresh().status, ChatStatus.REVEALED)
        self.assertEqual(self.credits.get_balances(self.boy)["coins"], 0)

    def test_pay_with_coin_insufficient_rejected(self) -> None:
        self._make_eligible()
        self._decide(self.boy, DecisionChoice.REVEAL)
        self._decide(self.girl, DecisionChoice.REVEAL)
        result = self.pay.pay_with_coin(
            user=self.boy, chat_id=str(self.chat.id), purpose=PaymentPurpose.REVEAL
        )
        self.assertEqual(result.error_code, "INSUFFICIENT_COINS")


@override_settings(ENDGAME_PAYMENT_BYPASS=True)
class EndgamePaymentBypassTests(TestCase):
    """TEMPORARY dev/test switch (FE bridge [00054]): a mutual payable decision
    completes WITHOUT any coins or Play purchase."""

    def setUp(self) -> None:
        cache.clear()
        notif = mock.MagicMock()
        self.chats = ChatService(notification_service=notif)
        self.reveal = RevealService(chat_service=self.chats, notification_service=notif)
        self.boy = _user(Gender.MALE)
        self.girl = _user(Gender.FEMALE)
        self.chat = self.chats.create_chat(self.boy, self.girl).data

    def _eligible(self) -> None:
        Chat.objects.filter(id=self.chat.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )
        self.chat.refresh_from_db()

    def _decide(self, user, choice):
        return self.reveal.submit_decision(
            chat_id=str(self.chat.id), user=user, choice=choice
        )

    def test_mutual_reveal_completes_without_payment(self) -> None:
        self._eligible()
        self._decide(self.boy, DecisionChoice.REVEAL)
        self._decide(self.girl, DecisionChoice.REVEAL)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, ChatStatus.REVEALED)

    def test_mutual_extend_completes_without_payment(self) -> None:
        self._eligible()
        self.chats.expire_chat(str(self.chat.id))
        self._decide(self.boy, DecisionChoice.EXTEND)
        self._decide(self.girl, DecisionChoice.EXTEND)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, ChatStatus.EXTENDED)

    def test_safe_reveal_enters_safe_decision_without_payment(self) -> None:
        self._eligible()
        self._decide(self.boy, DecisionChoice.REVEAL)
        self._decide(self.girl, DecisionChoice.SAFE_REVEAL)
        round_ = DecisionRound.objects.filter(chat=self.chat).latest("created_at")
        self.assertEqual(round_.final_call, FinalCall.SAFE_REVEAL)
        self.assertEqual(round_.phase, DecisionRoundPhase.SAFE_DECISION)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, ChatStatus.ACTIVE)  # girl still decides

    def test_disabled_flag_keeps_payment_gate(self) -> None:
        with override_settings(ENDGAME_PAYMENT_BYPASS=False):
            self._eligible()
            self._decide(self.boy, DecisionChoice.REVEAL)
            self._decide(self.girl, DecisionChoice.REVEAL)
            round_ = DecisionRound.objects.filter(chat=self.chat).latest("created_at")
            self.assertEqual(round_.phase, DecisionRoundPhase.PAYMENT)
            self.chat.refresh_from_db()
            self.assertEqual(self.chat.status, ChatStatus.ACTIVE)
