"""URL routes for the payments API."""

from __future__ import annotations

from django.urls import path

from apps.payments.api.views import (
    ChatPaymentStatusView,
    PayWithCoinView,
    PaymentDetailView,
    StoreCatalogView,
    StorePurchaseView,
    VerifyPurchaseView,
    WalletView,
)

app_name = "payments"

urlpatterns = [
    path(
        "payments/verify-purchase",
        VerifyPurchaseView.as_view(),
        name="verify-purchase",
    ),
    path("payments/pay-with-coin", PayWithCoinView.as_view(), name="pay-with-coin"),
    path("store/catalog", StoreCatalogView.as_view(), name="store-catalog"),
    path("store/purchase", StorePurchaseView.as_view(), name="store-purchase"),
    path("wallet", WalletView.as_view(), name="wallet"),
    path(
        "chats/<uuid:chat_id>/payments/status",
        ChatPaymentStatusView.as_view(),
        name="chat-status",
    ),
    # Keep the {id} route last so it does not shadow the literal payment routes.
    path("payments/<uuid:payment_id>", PaymentDetailView.as_view(), name="detail"),
]
