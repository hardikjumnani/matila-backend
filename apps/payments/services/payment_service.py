"""
Payment service.

Owns ``payments`` (an append-only ledger) and orchestrates money/coin flows for
the decision phase. Google Play is the only provider: chat-bound purchases
(SAFE_REVEAL / CHAT_EXTENSION) and store bundles (CREDIT_PURCHASE) are verified
against the Play Developer API; standard reveals are funded by coins. All effects
mark the payer's side on the active DecisionRound via RevealService. Idempotent on
the (unique) purchase token. See docs/REVEAL_FLOW_SPEC.md.

``PAYMENTS_DEV_BYPASS`` (dev only) skips the Play verification call so the harness
can drive purchases with placeholder tokens; it never runs in production.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import IntegrityError
from apps.common.results import ServiceResult
from apps.configuration.constants import FeatureFlagKey
from apps.payments.constants import (
    PLAY_PRODUCT_TO_PURPOSE,
    SAFE_REVEAL_SKU_BY_GENDER,
)
from apps.payments.enums import (
    CoinLedgerReason,
    CoinType,
    PaymentInitiatedFrom,
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
)
from apps.payments.models import Payment
from apps.users.models import User

logger = logging.getLogger(__name__)

_CURRENCY = "INR"

# Chat-bound payable purposes and the FinalCall each corresponds to.
_CHAT_BOUND = (PaymentPurpose.SAFE_REVEAL, PaymentPurpose.CHAT_EXTENSION)
_PURPOSE_TO_FINAL = {
    PaymentPurpose.SAFE_REVEAL: "SAFE_REVEAL",
    PaymentPurpose.CHAT_EXTENSION: "EXTEND",
    PaymentPurpose.REVEAL: "REVEAL",  # coin-funded (pay-with-coin), no money SKU
}


class PaymentService:
    """Google Play purchase verification, coin flows, and round progression."""

    def __init__(
        self,
        *,
        configuration_service=None,
        chat_service=None,
        reveal_service=None,
        credit_service=None,
        notification_service=None,
    ) -> None:
        if configuration_service is None:
            from apps.configuration.services.configuration_service import (
                ConfigurationService,
            )

            configuration_service = ConfigurationService()
        if chat_service is None:
            from apps.chats.services.chat_service import ChatService

            chat_service = ChatService()
        if reveal_service is None:
            from apps.reveal.services.reveal_service import RevealService

            reveal_service = RevealService()
        if credit_service is None:
            from apps.payments.services.credit_service import CreditService

            credit_service = CreditService()
        if notification_service is None:
            from apps.notifications.services.notification_service import (
                NotificationService,
            )

            notification_service = NotificationService()
        self._config = configuration_service
        self._chats = chat_service
        self._reveal = reveal_service
        self._credits = credit_service
        self._notifications = notification_service

    # -- Amount / context ---------------------------------------------------

    def _resolve_amount(self, chat, purpose, user) -> ServiceResult[int]:
        if purpose == PaymentPurpose.REVEAL:
            return ServiceResult.ok(self._config.get_reveal_price_paise())
        if purpose == PaymentPurpose.SAFE_REVEAL:
            from apps.users.enums import Gender

            if user.gender == Gender.FEMALE:
                return ServiceResult.ok(
                    self._config.get_safe_reveal_female_price_paise()
                )
            return ServiceResult.ok(self._config.get_safe_reveal_male_price_paise())
        if purpose == PaymentPurpose.CHAT_EXTENSION:
            return ServiceResult.ok(self._config.get_chat_extension_price_paise())
        return ServiceResult.fail("VALIDATION_ERROR", "Unknown payment purpose.")

    def _validate_payable_context(self, chat, user, purpose) -> ServiceResult[None]:
        """Ensure an active PAYMENT round matches this purpose and the user has
        not already paid this cycle."""
        expected = _PURPOSE_TO_FINAL.get(purpose)
        if self._reveal.get_active_final_call(chat) != expected:
            return ServiceResult.fail(
                "CONFLICT", "No active payment is expected for this action."
            )
        if self._reveal.has_paid(chat, user):
            return ServiceResult.fail("CONFLICT", "You have already paid for this.")
        return ServiceResult.ok(None)

    # -- Google Play (chat-bound: SAFE_REVEAL / CHAT_EXTENSION) --------------

    def verify_google_play_purchase(
        self,
        *,
        user: User,
        chat_id: str,
        purpose: PaymentPurpose | str,
        product_id: str,
        purchase_token: str,
        initiated_from: PaymentInitiatedFrom | str,
    ) -> ServiceResult[Payment]:
        from apps.payments import gateway_play

        if not self._config.is_feature_enabled(FeatureFlagKey.PAYMENTS_ENABLED):
            return ServiceResult.fail("FORBIDDEN", "Payments are currently disabled.")
        if purpose not in _CHAT_BOUND:
            return ServiceResult.fail(
                "VALIDATION_ERROR", "This purpose is not purchasable here."
            )
        if PLAY_PRODUCT_TO_PURPOSE.get(product_id) != purpose:
            return ServiceResult.fail(
                "VALIDATION_ERROR", "Product does not match the requested purpose."
            )
        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        if not self._chats.is_participant(chat, user):
            return ServiceResult.fail("FORBIDDEN", "You are not in this chat.")
        if purpose == PaymentPurpose.SAFE_REVEAL:
            if product_id != SAFE_REVEAL_SKU_BY_GENDER.get(str(user.gender)):
                return ServiceResult.fail(
                    "VALIDATION_ERROR", "Wrong safe-reveal product for your role."
                )

        existing = Payment.objects.filter(provider_payment_id=purchase_token).first()
        if existing is not None:
            return ServiceResult.ok(existing)

        ctx = self._validate_payable_context(chat, user, purpose)
        if ctx.failed:
            return ServiceResult.fail(ctx.error_code, ctx.error_message)

        amount_result = self._resolve_amount(chat, purpose, user)
        if amount_result.failed:
            return ServiceResult.fail(
                amount_result.error_code, amount_result.error_message
            )

        try:
            info = self._verify_token(gateway_play, product_id, purchase_token)
        except gateway_play.InvalidPurchase:
            return ServiceResult.fail("VALIDATION_ERROR", "Purchase verification failed.")
        except gateway_play.PlayGatewayError:
            return ServiceResult.fail(
                "INTERNAL_SERVER_ERROR", "Could not verify the purchase."
            )

        payment, created = self._record_play_success(
            user=user,
            chat=chat,
            purpose=purpose,
            amount=amount_result.data,
            initiated_from=initiated_from,
            product_id=product_id,
            purchase_token=purchase_token,
            order_id=info.get("orderId", ""),
        )
        if created:
            self._handle_successful_payment(payment)
        return ServiceResult.ok(payment)

    # -- Store bundle purchase (grants reveal_coins) ------------------------

    def purchase_bundle(
        self, *, user: User, product_id: str, purchase_token: str
    ) -> ServiceResult[dict]:
        from apps.payments import gateway_play

        if not self._config.is_feature_enabled(FeatureFlagKey.PAYMENTS_ENABLED):
            return ServiceResult.fail("FORBIDDEN", "Payments are currently disabled.")
        if PLAY_PRODUCT_TO_PURPOSE.get(product_id) != PaymentPurpose.CREDIT_PURCHASE:
            return ServiceResult.fail("VALIDATION_ERROR", "Unknown store product.")
        bundle = self._config.get_bundle_by_sku(product_id)
        if bundle is None:
            return ServiceResult.fail("VALIDATION_ERROR", "Unknown store product.")

        existing = Payment.objects.filter(provider_payment_id=purchase_token).first()
        if existing is not None:
            return ServiceResult.ok(
                {
                    "payment_id": str(existing.id),
                    "coins_added": int(existing.metadata.get("coins", 0)),
                    "balances": self._credits.get_balances(user),
                }
            )

        try:
            info = self._verify_token(gateway_play, product_id, purchase_token)
        except gateway_play.InvalidPurchase:
            return ServiceResult.fail("VALIDATION_ERROR", "Purchase verification failed.")
        except gateway_play.PlayGatewayError:
            return ServiceResult.fail(
                "INTERNAL_SERVER_ERROR", "Could not verify the purchase."
            )

        coins = int(bundle["coins"])
        try:
            payment = Payment.objects.create(
                user=user,
                chat=None,
                purpose=PaymentPurpose.CREDIT_PURCHASE,
                amount_in_paise=int(bundle["price_paise"]),
                currency=_CURRENCY,
                provider=PaymentProvider.GOOGLE_PLAY,
                provider_order_id=info.get("orderId") or None,
                provider_payment_id=purchase_token,
                status=PaymentStatus.SUCCESS,
                initiated_from=PaymentInitiatedFrom.STORE,
                metadata={"product_id": product_id, "coins": coins},
            )
        except IntegrityError:
            payment = Payment.objects.get(provider_payment_id=purchase_token)
        self._credits.credit(
            user=user,
            coin_type=CoinType.REVEAL,
            amount=coins,
            reason=CoinLedgerReason.BUNDLE_PURCHASE,
            idempotency_key=f"bundle:{purchase_token}",
            payment=payment,
        )
        return ServiceResult.ok(
            {
                "payment_id": str(payment.id),
                "coins_added": coins,
                "balances": self._credits.get_balances(user),
            }
        )

    def _verify_token(self, gateway_play, product_id: str, purchase_token: str) -> dict:
        """Verify a Play purchase token, or synthesize a result under dev bypass."""
        if settings.PAYMENTS_DEV_BYPASS:
            return {"orderId": f"dev_{purchase_token}"}
        return gateway_play.verify_product_purchase(
            product_id=product_id, purchase_token=purchase_token
        )

    # -- Pay with coin (chat-bound reveal / safe reveal) --------------------

    def pay_with_coin(
        self, *, user: User, chat_id: str, purpose: PaymentPurpose | str
    ) -> ServiceResult[dict]:
        from apps.users.enums import Gender

        if purpose not in (PaymentPurpose.REVEAL, PaymentPurpose.SAFE_REVEAL):
            return ServiceResult.fail(
                "VALIDATION_ERROR", "Only reveals can be paid with coins."
            )
        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        if not self._chats.is_participant(chat, user):
            return ServiceResult.fail("FORBIDDEN", "You are not in this chat.")

        ctx = self._validate_payable_context(chat, user, purpose)
        if ctx.failed:
            return ServiceResult.fail(ctx.error_code, ctx.error_message)

        if purpose == PaymentPurpose.SAFE_REVEAL and user.gender == Gender.FEMALE:
            coin_type = CoinType.SAFE_REVEAL
        else:
            coin_type = CoinType.REVEAL

        round_id = self._reveal.active_round_id(chat)
        consumed = self._credits.consume(
            user=user,
            coin_type=coin_type,
            idempotency_key=f"consume:{round_id}:{user.id}:{coin_type}",
            chat=chat,
        )
        if consumed.failed:
            return ServiceResult.fail(consumed.error_code, consumed.error_message)

        self._reveal.record_payment(
            chat_id=str(chat.id), user=user, purpose=purpose, paid_with_coin=True
        )
        return ServiceResult.ok(
            {"paid_with_coin": True, "balances": self._credits.get_balances(user)}
        )

    # -- Ledger internals ---------------------------------------------------

    def _record_play_success(
        self,
        *,
        user,
        chat,
        purpose,
        amount,
        initiated_from,
        product_id,
        purchase_token,
        order_id,
    ) -> tuple[Payment, bool]:
        try:
            payment = Payment.objects.create(
                user=user,
                chat=chat,
                purpose=purpose,
                amount_in_paise=amount,
                currency=_CURRENCY,
                provider=PaymentProvider.GOOGLE_PLAY,
                provider_order_id=order_id or None,
                provider_payment_id=purchase_token,
                status=PaymentStatus.SUCCESS,
                initiated_from=initiated_from,
                metadata={"product_id": product_id},
            )
            return payment, True
        except IntegrityError:
            return Payment.objects.get(provider_payment_id=purchase_token), False

    def _handle_successful_payment(self, payment: Payment) -> None:
        if payment.purpose in _CHAT_BOUND and payment.chat_id is not None:
            self._reveal.record_payment(
                chat_id=str(payment.chat_id),
                user=payment.user,
                purpose=payment.purpose,
                paid_with_coin=False,
            )

    # -- Reads --------------------------------------------------------------

    def get_payment(self, *, payment_id: str, user: User) -> Payment | None:
        return Payment.objects.filter(id=payment_id, user=user).first()

    def get_chat_payment_status(self, *, chat_id: str, user: User) -> dict:
        state = self._reveal.get_decision_state(chat_id=chat_id, user=user)
        data = state.data if state.success else {}
        data["balances"] = self._credits.get_balances(user)
        return data
