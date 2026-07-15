"""URL routes for the payments API."""

from __future__ import annotations

from django.urls import path

from apps.payments.api.views import (
    ChatPaymentStatusView,
    CreateOrderView,
    PaymentDetailView,
    PaymentWebhookView,
    VerifyPaymentView,
)

app_name = "payments"

urlpatterns = [
    path("payments/create-order", CreateOrderView.as_view(), name="create-order"),
    path("payments/verify", VerifyPaymentView.as_view(), name="verify"),
    path("payments/webhook", PaymentWebhookView.as_view(), name="webhook"),
    path(
        "chats/<uuid:chat_id>/payments/status",
        ChatPaymentStatusView.as_view(),
        name="chat-status",
    ),
    # Keep the {id} route last so it does not shadow the literal payment routes.
    path("payments/<uuid:payment_id>", PaymentDetailView.as_view(), name="detail"),
]
