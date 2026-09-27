"""
Payments API views.

The webhook is the one unauthenticated endpoint: it reads the RAW request body
and verifies the Razorpay signature (inside the service) BEFORE any parsing, so
an unsigned or tampered payload never reaches business logic. All other
endpoints require authentication; ownership/participation is enforced by the
service or the chat-participant permission.
"""

from __future__ import annotations

import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chats.permissions import IsChatParticipant
from apps.common.responses import envelope_error, service_failure_response
from apps.payments.api.serializers import (
    CreateOrderRequestSerializer,
    PayWithCoinRequestSerializer,
    PaymentSerializer,
    StorePurchaseRequestSerializer,
    VerifyPaymentRequestSerializer,
    VerifyPurchaseRequestSerializer,
)
from apps.payments.services.credit_service import CreditService
from apps.payments.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


class CreateOrderView(APIView):
    """POST /payments/create-order — create (or reuse) a Razorpay order."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = PaymentService()

    @extend_schema(
        request=CreateOrderRequestSerializer,
        responses=OpenApiResponse(description="Razorpay order details."),
    )
    def post(self, request: Request) -> Response:
        serializer = CreateOrderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.create_order(
            user=request.user,
            chat_id=str(data["chat_id"]),
            purpose=data["purpose"],
            initiated_from=data["initiated_from"],
        )
        if result.failed:
            return service_failure_response(result)
        return Response(result.data, status=201)


class VerifyPaymentView(APIView):
    """POST /payments/verify — verify a client-reported payment signature."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = PaymentService()

    @extend_schema(request=VerifyPaymentRequestSerializer, responses=PaymentSerializer)
    def post(self, request: Request) -> Response:
        serializer = VerifyPaymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.verify_payment(
            order_id=data["razorpay_order_id"],
            payment_id=data["razorpay_payment_id"],
            signature=data["razorpay_signature"],
        )
        if result.failed:
            return service_failure_response(result)
        return Response(PaymentSerializer(result.data).data)


class VerifyPurchaseView(APIView):
    """POST /payments/verify-purchase — verify a Google Play purchase token."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = PaymentService()

    @extend_schema(request=VerifyPurchaseRequestSerializer, responses=PaymentSerializer)
    def post(self, request: Request) -> Response:
        serializer = VerifyPurchaseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.verify_google_play_purchase(
            user=request.user,
            chat_id=str(data["chat_id"]),
            purpose=data["purpose"],
            product_id=data["product_id"],
            purchase_token=data["purchase_token"],
            initiated_from=data["initiated_from"],
        )
        if result.failed:
            return service_failure_response(result)
        return Response(PaymentSerializer(result.data).data, status=201)


class PaymentWebhookView(APIView):
    """POST /payments/webhook — Razorpay webhook (unauthenticated, signed)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = PaymentService()

    @extend_schema(
        request=None, responses=OpenApiResponse(description="Webhook acknowledged.")
    )
    def post(self, request: Request) -> Response:
        # Read the raw body FIRST (before any parsing) so the exact bytes are
        # available for signature verification.
        raw_body = request.body.decode("utf-8", errors="replace")
        signature = request.headers.get("X-Razorpay-Signature", "")
        result = self.service.process_webhook(body=raw_body, signature=signature)
        if result.failed:
            return service_failure_response(result)
        return Response(result.data)


class PaymentDetailView(APIView):
    """GET /payments/{id} — the caller's own payment."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = PaymentService()

    @extend_schema(responses=PaymentSerializer)
    def get(self, request: Request, payment_id: str) -> Response:
        payment = self.service.get_payment(payment_id=payment_id, user=request.user)
        if payment is None:
            return envelope_error("RESOURCE_NOT_FOUND", "Payment not found.", 404)
        return Response(PaymentSerializer(payment).data)


class ChatPaymentStatusView(APIView):
    """GET /chats/{id}/payments/status — decision + payment state for a chat."""

    permission_classes = [IsAuthenticated, IsChatParticipant]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = PaymentService()

    @extend_schema(responses=OpenApiResponse(description="Chat payment status."))
    def get(self, request: Request, chat_id: str) -> Response:
        return Response(
            self.service.get_chat_payment_status(chat_id=chat_id, user=request.user)
        )


class StoreCatalogView(APIView):
    """GET /store/catalog — the standard-reveal coin bundles."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiResponse(description="Store catalog."))
    def get(self, request: Request) -> Response:
        from apps.configuration.services.configuration_service import (
            ConfigurationService,
        )

        config = ConfigurationService()
        return Response(
            {
                "standard_reveal_bundles": config.get_standard_reveal_bundles(),
                "safe_reveal": {
                    "female_price_paise": config.get_safe_reveal_female_price_paise(),
                    "male_price_paise": config.get_safe_reveal_male_price_paise(),
                },
            }
        )


class StorePurchaseView(APIView):
    """POST /store/purchase — verify a bundle purchase and grant reveal_coins."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = PaymentService()

    @extend_schema(
        request=StorePurchaseRequestSerializer,
        responses=OpenApiResponse(description="Coins granted."),
    )
    def post(self, request: Request) -> Response:
        serializer = StorePurchaseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.purchase_bundle(
            user=request.user,
            product_id=data["product_id"],
            purchase_token=data["purchase_token"],
        )
        if result.failed:
            return service_failure_response(result)
        return Response(result.data, status=201)


class PayWithCoinView(APIView):
    """POST /payments/pay-with-coin — spend a coin for a reveal / safe reveal."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = PaymentService()

    @extend_schema(
        request=PayWithCoinRequestSerializer,
        responses=OpenApiResponse(description="Coin spent."),
    )
    def post(self, request: Request) -> Response:
        serializer = PayWithCoinRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.pay_with_coin(
            user=request.user,
            chat_id=str(data["chat_id"]),
            purpose=data["purpose"],
        )
        if result.failed:
            return service_failure_response(result)
        return Response(result.data)


class WalletView(APIView):
    """GET /wallet — the caller's coin balances."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiResponse(description="Coin balances."))
    def get(self, request: Request) -> Response:
        return Response(CreditService().get_balances(request.user))
