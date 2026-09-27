"""
Payments domain models.

``Payment`` is an append-only financial ledger. Rows are never updated in place
except for the controlled status/provider-id transitions driven by
PaymentService as Razorpay reports outcomes. Provider identifiers are uniquely
constrained so webhook and client-verify paths remain idempotent.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel

from .enums import (
    CoinLedgerReason,
    CoinType,
    PaymentInitiatedFrom,
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
)


class Payment(UUIDModel):
    # PROTECT: financial records must survive even if a user/chat removal were
    # ever attempted; deletion must be an explicit, deliberate operation.
    user = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    # Null for store bundle (CREDIT_PURCHASE) payments, which are not chat-bound.
    chat = models.ForeignKey(
        "chats.Chat",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )

    purpose = models.CharField(max_length=15, choices=PaymentPurpose.choices)
    amount_in_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="INR")

    provider = models.CharField(
        max_length=15,
        choices=PaymentProvider.choices,
        default=PaymentProvider.RAZORPAY,
    )
    # Unique among non-null values; NULLs permitted before the order/payment is
    # created at the provider. Enables idempotent webhook processing.
    provider_order_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )
    provider_payment_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )
    provider_signature = models.CharField(max_length=512, blank=True, default="")

    status = models.CharField(
        max_length=10,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    initiated_from = models.CharField(
        max_length=15, choices=PaymentInitiatedFrom.choices
    )
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    status_changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payments"
        ordering = ["-created_at"]
        indexes = [
            # "Have both users paid for this purpose on this chat?" lookups.
            models.Index(
                fields=["chat", "purpose", "status"],
                name="idx_payment_chat_purpose",
            ),
            models.Index(fields=["user", "status"], name="idx_payment_user_status"),
        ]

    def __str__(self) -> str:
        return (
            f"Payment<{self.id}> {self.purpose} {self.status} {self.amount_in_paise}p"
        )


class Wallet(UUIDModel):
    """Per-user coin balances. Mutated only via CreditService, which writes an
    idempotent CoinLedger row for every change (never bare balance edits)."""

    user = models.OneToOneField(
        "users.User",
        on_delete=models.PROTECT,
        related_name="wallet",
    )
    reveal_coins = models.PositiveIntegerField(default=0)
    safe_reveal_coins = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wallets"

    def __str__(self) -> str:
        return (
            f"Wallet<{self.id}> user={self.user_id} "
            f"reveal={self.reveal_coins} safe={self.safe_reveal_coins}"
        )


class CoinLedger(UUIDModel):
    """Append-only wallet ledger. ``idempotency_key`` is unique so a retried
    credit/consume can never double-apply."""

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="ledger",
    )
    coin_type = models.CharField(max_length=15, choices=CoinType.choices)
    delta = models.IntegerField()  # +N credit/purchase, -1 consume
    balance_after = models.PositiveIntegerField()
    reason = models.CharField(max_length=25, choices=CoinLedgerReason.choices)

    chat = models.ForeignKey(
        "chats.Chat",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="coin_ledger",
    )
    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="coin_ledger",
    )
    # Deterministic key deduping retries: e.g. "bundle:<token>",
    # "cancel:<round>:<user>", "consume:<round>:<user>:<coin_type>".
    idempotency_key = models.CharField(max_length=255, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "coin_ledger"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "coin_type"], name="idx_ledger_wallet_coin"),
        ]

    def __str__(self) -> str:
        return (
            f"CoinLedger<{self.id}> {self.coin_type} {self.delta:+d} "
            f"-> {self.balance_after} ({self.reason})"
        )
