"""Serializers for the payments API."""

from __future__ import annotations

from rest_framework import serializers

from apps.payments.enums import PaymentInitiatedFrom, PaymentPurpose
from apps.payments.models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    """Read representation of a payment (provider signature is never exposed)."""

    chat_id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "chat_id",
            "user_id",
            "purpose",
            "amount_in_paise",
            "currency",
            "provider",
            "provider_order_id",
            "provider_payment_id",
            "status",
            "initiated_from",
            "created_at",
            "status_changed_at",
        ]
        read_only_fields = fields


class CreateOrderRequestSerializer(serializers.Serializer):
    chat_id = serializers.UUIDField()
    purpose = serializers.ChoiceField(choices=PaymentPurpose.choices)
    initiated_from = serializers.ChoiceField(choices=PaymentInitiatedFrom.choices)


class VerifyPaymentRequestSerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField()
    razorpay_payment_id = serializers.CharField()
    razorpay_signature = serializers.CharField()


class VerifyPurchaseRequestSerializer(serializers.Serializer):
    """Google Play: a client-reported purchase token to verify server-side."""

    chat_id = serializers.UUIDField()
    purpose = serializers.ChoiceField(choices=PaymentPurpose.choices)
    product_id = serializers.CharField()
    purchase_token = serializers.CharField()
    initiated_from = serializers.ChoiceField(
        choices=PaymentInitiatedFrom.choices,
        required=False,
        default=PaymentInitiatedFrom.CHAT_SCREEN,
    )


class StorePurchaseRequestSerializer(serializers.Serializer):
    """Google Play: buy a standard-reveal bundle → grants reveal_coins."""

    product_id = serializers.CharField()
    purchase_token = serializers.CharField()


class PayWithCoinRequestSerializer(serializers.Serializer):
    chat_id = serializers.UUIDField()
    purpose = serializers.ChoiceField(
        choices=[
            (PaymentPurpose.REVEAL, "Reveal"),
            (PaymentPurpose.SAFE_REVEAL, "Safe reveal"),
        ]
    )
