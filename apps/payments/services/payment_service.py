"""
Payment service.

Owns ``payments`` (an append-only ledger). Creates Razorpay orders, verifies
client-reported payments and webhooks, and triggers the downstream effects:
completing a reveal (both users paid) or extending an anonymous chat (both users
paid). Verification and webhook handling are idempotent, so the client-verify
and webhook paths can both fire for the same payment without double effects.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.chats.enums import ChatStatus
from apps.common.results import ServiceResult
from apps.configuration.constants import FeatureFlagKey
from apps.payments import gateway
from apps.payments.enums import (
    PaymentInitiatedFrom,
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
)
from apps.payments.models import Payment
from apps.users.models import User

logger = logging.getLogger(__name__)

_CURRENCY = "INR"
_SUCCESS_EVENTS = ("payment.captured", "payment.authorized")
_FAILURE_EVENTS = ("payment.failed",)


class PaymentService:
    """Razorpay order lifecycle and payment-driven side effects."""

    def __init__(
        self,
        *,
        configuration_service=None,
        chat_service=None,
        reveal_service=None,
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
        if notification_service is None:
            from apps.notifications.services.notification_service import (
                NotificationService,
            )

            notification_service = NotificationService()
        self._config = configuration_service
        self._chats = chat_service
        self._reveal = reveal_service
        self._notifications = notification_service

    # -- Order creation -----------------------------------------------------

    def create_order(
        self,
        *,
        user: User,
        chat_id: str,
        purpose: PaymentPurpose | str,
        initiated_from: PaymentInitiatedFrom | str,
    ) -> ServiceResult[dict]:
        """Create (or reuse a pending) Razorpay order for reveal/extension."""
        if not self._config.is_feature_enabled(FeatureFlagKey.PAYMENTS_ENABLED):
            return ServiceResult.fail("FORBIDDEN", "Payments are currently disabled.")

        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        if not self._chats.is_participant(chat, user):
            return ServiceResult.fail("FORBIDDEN", "You are not in this chat.")

        # Prevent a double charge within the current window. Reveal is one-time
        # (ever); a 2-day extension is one-time PER expiry cycle, so it can be
        # bought again after the chat expires anew.
        if self._already_paid(user, chat, purpose):
            return ServiceResult.fail("CONFLICT", "You have already paid for this.")

        amount_result = self._resolve_amount(chat, purpose)
        if amount_result.failed:
            return ServiceResult.fail(
                amount_result.error_code, amount_result.error_message
            )
        amount = amount_result.data

        # Idempotent reuse: an existing pending order for this (user, chat,
        # purpose) is returned rather than creating a duplicate.
        existing = Payment.objects.filter(
            user=user,
            chat=chat,
            purpose=purpose,
            status=PaymentStatus.PENDING,
            provider_order_id__isnull=False,
        ).first()
        if existing is not None:
            return ServiceResult.ok(self._order_payload(existing))

        payment = Payment.objects.create(
            user=user,
            chat=chat,
            purpose=purpose,
            amount_in_paise=amount,
            currency=_CURRENCY,
            initiated_from=initiated_from,
            status=PaymentStatus.PENDING,
        )

        # Dev bypass: skip the real gateway and hand back a synthetic order id.
        # The client sees ``dev_bypass: true`` (via _order_payload) and proceeds
        # straight to verify.
        if settings.PAYMENTS_DEV_BYPASS:
            payment.provider_order_id = f"dev_order_{payment.id}"
            payment.save(update_fields=["provider_order_id"])
            return ServiceResult.ok(self._order_payload(payment))

        try:
            order = gateway.create_order(
                amount_in_paise=amount,
                currency=_CURRENCY,
                receipt=str(payment.id),
                notes={"chat_id": str(chat.id), "purpose": str(purpose)},
            )
        except gateway.PaymentGatewayError as exc:
            payment.status = PaymentStatus.FAILED
            payment.save(update_fields=["status", "status_changed_at"])
            logger.error("Order creation failed for payment %s: %s", payment.id, exc)
            return ServiceResult.fail(
                "INTERNAL_SERVER_ERROR", "Could not create the payment order."
            )

        payment.provider_order_id = order["id"]
        payment.save(update_fields=["provider_order_id"])
        return ServiceResult.ok(self._order_payload(payment))

    def _already_paid(self, user, chat, purpose) -> bool:
        """Whether a new order for (user, chat, purpose) must be rejected.

        Reveal is one-time ever. A 2-day extension is one-time **per expiry
        cycle**: extensions are only bought while the chat is EXPIRED, so a
        SUCCESS extension payment counts only if it was made since the chat's
        current EXPIRED transition (``status_changed_at``). Once the chat expires
        again, a fresh extension can be purchased — enabling indefinite cycles.
        """
        qs = Payment.objects.filter(
            user=user, chat=chat, purpose=purpose, status=PaymentStatus.SUCCESS
        )
        if purpose == PaymentPurpose.CHAT_EXTENSION:
            qs = qs.filter(created_at__gte=chat.status_changed_at)
        return qs.exists()

    def _resolve_amount(
        self, chat, purpose: PaymentPurpose | str
    ) -> ServiceResult[int]:
        if purpose == PaymentPurpose.REVEAL:
            if chat.status == ChatStatus.REVEALED:
                return ServiceResult.fail("CONFLICT", "This chat is already revealed.")
            if not self._reveal.is_mutual(str(chat.id)):
                return ServiceResult.fail(
                    "VALIDATION_ERROR",
                    "Reveal payment requires mutual reveal intent.",
                )
            return ServiceResult.ok(self._config.get_reveal_price_paise())
        if purpose == PaymentPurpose.CHAT_EXTENSION:
            if chat.status != ChatStatus.EXPIRED:
                return ServiceResult.fail(
                    "CONFLICT", "Chat extension is only available after expiry."
                )
            return ServiceResult.ok(self._config.get_chat_extension_price_paise())
        return ServiceResult.fail("VALIDATION_ERROR", "Unknown payment purpose.")

    def _order_payload(self, payment: Payment) -> dict:
        return {
            "payment_id": str(payment.id),
            "order_id": payment.provider_order_id,
            "amount_in_paise": payment.amount_in_paise,
            "currency": payment.currency,
            "razorpay_key_id": settings.RAZORPAY_KEY_ID,
            "purpose": payment.purpose,
            # Signals the client to skip the Razorpay SDK and go straight to
            # verify. Always False in production (gateway is real there).
            "dev_bypass": settings.PAYMENTS_DEV_BYPASS,
        }

    # -- Verification -------------------------------------------------------

    def verify_payment(
        self, *, order_id: str, payment_id: str, signature: str
    ) -> ServiceResult[Payment]:
        """Verify a client-reported payment signature and apply its effects."""
        # Dev bypass: accept the client-reported payment without contacting the
        # gateway (order/payment ids and signature may be placeholders).
        if not settings.PAYMENTS_DEV_BYPASS:
            try:
                gateway.verify_payment_signature(
                    order_id=order_id, payment_id=payment_id, signature=signature
                )
            except gateway.InvalidPaymentSignature:
                return ServiceResult.fail(
                    "VALIDATION_ERROR", "Payment signature verification failed."
                )
        else:
            # The client sends the same placeholder for every bypassed payment,
            # which would collide on the unique provider_payment_id column;
            # derive a unique id from the (unique) order id instead.
            payment_id = f"dev_pay_{order_id}"

        payment, already_done = self._apply_success(
            order_id=order_id, payment_id=payment_id, signature=signature
        )
        if payment is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Payment not found.")
        if not already_done:
            self._handle_successful_payment(payment)
        return ServiceResult.ok(payment)

    def process_webhook(self, *, body: str, signature: str) -> ServiceResult[dict]:
        """Process a Razorpay webhook idempotently."""
        try:
            gateway.verify_webhook_signature(body=body, signature=signature)
        except gateway.InvalidPaymentSignature:
            return ServiceResult.fail("UNAUTHORIZED", "Invalid webhook signature.")
        except gateway.PaymentGatewayError:
            return ServiceResult.fail(
                "INTERNAL_SERVER_ERROR", "Webhook processing is not configured."
            )

        try:
            payload = json.loads(body)
            event = payload.get("event", "")
            entity = payload["payload"]["payment"]["entity"]
            order_id = entity.get("order_id", "")
            payment_id = entity.get("id", "")
        except (ValueError, KeyError, TypeError):
            return ServiceResult.fail("VALIDATION_ERROR", "Malformed webhook payload.")

        if event in _SUCCESS_EVENTS:
            payment, already_done = self._apply_success(
                order_id=order_id, payment_id=payment_id, signature=""
            )
            if payment is not None and not already_done:
                self._handle_successful_payment(payment)
        elif event in _FAILURE_EVENTS:
            self._apply_failure(order_id=order_id)

        # Always acknowledge: unrecognized/unknown events must not trigger
        # Razorpay retries.
        return ServiceResult.ok({"event": event})

    # -- Google Play Billing -----------------------------------------------

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
        """Verify a Google Play purchase token and apply its effects.

        Play has no server-created order: the client buys via the Play SDK and
        reports the purchase token, which we verify against the Play Developer
        API. Idempotent on the (unique) purchase token, so a retry never
        double-grants. Reuses the same reveal/extension completion as Razorpay.
        """
        from apps.payments import gateway_play
        from apps.payments.constants import PLAY_PRODUCT_TO_PURPOSE

        if not self._config.is_feature_enabled(FeatureFlagKey.PAYMENTS_ENABLED):
            return ServiceResult.fail("FORBIDDEN", "Payments are currently disabled.")
        if PLAY_PRODUCT_TO_PURPOSE.get(product_id) != purpose:
            return ServiceResult.fail(
                "VALIDATION_ERROR", "Product does not match the requested purpose."
            )

        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        if not self._chats.is_participant(chat, user):
            return ServiceResult.fail("FORBIDDEN", "You are not in this chat.")

        # Idempotency: this exact purchase token was already recorded.
        existing = Payment.objects.filter(provider_payment_id=purchase_token).first()
        if existing is not None:
            return ServiceResult.ok(existing)

        # Reveal is one-time; a 2-day extension is one-time per expiry cycle.
        if self._already_paid(user, chat, purpose):
            return ServiceResult.fail("CONFLICT", "You have already paid for this.")

        # Eligibility + amount (REVEAL needs mutual intent; EXTENSION needs EXPIRED).
        amount_result = self._resolve_amount(chat, purpose)
        if amount_result.failed:
            return ServiceResult.fail(
                amount_result.error_code, amount_result.error_message
            )

        try:
            info = gateway_play.verify_product_purchase(
                product_id=product_id, purchase_token=purchase_token
            )
        except gateway_play.InvalidPurchase:
            return ServiceResult.fail(
                "VALIDATION_ERROR", "Purchase verification failed."
            )
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
        """Create a SUCCESS payment for a verified Play purchase, idempotent on
        the unique purchase token. Returns (payment, created)."""
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
            # Concurrent verify of the same token lost the race; return the winner.
            return Payment.objects.get(provider_payment_id=purchase_token), False

    @transaction.atomic
    def _apply_success(
        self, *, order_id: str, payment_id: str, signature: str
    ) -> tuple[Payment | None, bool]:
        """Mark a payment SUCCESS. Returns (payment, already_processed)."""
        payment = (
            Payment.objects.select_for_update()
            .filter(provider_order_id=order_id)
            .first()
        )
        if payment is None:
            return None, False
        if payment.status == PaymentStatus.SUCCESS:
            return payment, True

        payment.status = PaymentStatus.SUCCESS
        payment.provider_payment_id = payment_id or payment.provider_payment_id
        if signature:
            payment.provider_signature = signature
        payment.save(
            update_fields=[
                "status",
                "provider_payment_id",
                "provider_signature",
                "status_changed_at",
            ]
        )
        return payment, False

    @transaction.atomic
    def _apply_failure(self, *, order_id: str) -> None:
        payment = (
            Payment.objects.select_for_update()
            .filter(provider_order_id=order_id)
            .first()
        )
        if payment is not None and payment.status == PaymentStatus.PENDING:
            payment.status = PaymentStatus.FAILED
            payment.save(update_fields=["status", "status_changed_at"])

    # -- Side effects -------------------------------------------------------

    def _handle_successful_payment(self, payment: Payment) -> None:
        if payment.purpose == PaymentPurpose.REVEAL:
            self._reveal.mark_intent_paid(
                chat_id=str(payment.chat_id), user=payment.user
            )
        elif payment.purpose == PaymentPurpose.CHAT_EXTENSION:
            self._maybe_extend_chat(str(payment.chat_id))

    def _maybe_extend_chat(self, chat_id: str) -> None:
        """Extend the chat once both participants have paid for the CURRENT cycle.

        Only extends from EXPIRED (idempotency: a second success — e.g. webhook
        after verify — cannot extend twice). Counts only extension payments made
        since this EXPIRED transition, so each 2-day cycle needs its own two
        payments and prior cycles never pre-satisfy a later one.
        """
        chat = self._chats.get_chat(chat_id)
        if chat is None or chat.status != ChatStatus.EXPIRED:
            return

        paid_users = (
            Payment.objects.filter(
                chat_id=chat_id,
                purpose=PaymentPurpose.CHAT_EXTENSION,
                status=PaymentStatus.SUCCESS,
                created_at__gte=chat.status_changed_at,
            )
            .values("user")
            .distinct()
            .count()
        )
        if paid_users < 2:
            return

        result = self._chats.extend_chat(chat_id)
        if result.success:
            self._notify_extended(chat_id)

    # -- Reads --------------------------------------------------------------

    def get_payment(self, *, payment_id: str, user: User) -> Payment | None:
        return Payment.objects.filter(id=payment_id, user=user).first()

    def get_chat_payment_status(self, *, chat_id: str, user: User) -> dict:
        def _stats(purpose: str) -> dict:
            qs = Payment.objects.filter(
                chat_id=chat_id, purpose=purpose, status=PaymentStatus.SUCCESS
            )
            return {
                "paid_count": qs.values("user").distinct().count(),
                "paid_by_me": qs.filter(user=user).exists(),
            }

        return {
            "reveal": _stats(PaymentPurpose.REVEAL),
            "extension": _stats(PaymentPurpose.CHAT_EXTENSION),
        }

    def _notify_extended(self, chat_id: str) -> None:
        from apps.chats.models import ChatParticipant

        for participant in ChatParticipant.objects.select_related("user").filter(
            chat_id=chat_id
        ):
            self._notifications.create_notification(
                user=participant.user,
                type="chat.extended",
                title="Your chat has been extended",
                body="You can keep chatting anonymously.",
                action_type="OPEN_CHAT",
                action_payload={"chat_id": str(chat_id)},
            )
