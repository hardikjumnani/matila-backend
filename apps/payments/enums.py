"""Enumerations owned by the payments domain."""

from __future__ import annotations

from django.db import models


class PaymentPurpose(models.TextChoices):
    REVEAL = "REVEAL", "Reveal"
    SAFE_REVEAL = "SAFE_REVEAL", "Safe reveal"
    CHAT_EXTENSION = "CHAT_EXTENSION", "Chat extension"
    CREDIT_PURCHASE = "CREDIT_PURCHASE", "Credit purchase"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    REFUNDED = "REFUNDED", "Refunded"


class PaymentProvider(models.TextChoices):
    GOOGLE_PLAY = "GOOGLE_PLAY", "Google Play"


class PaymentInitiatedFrom(models.TextChoices):
    CHAT_SCREEN = "CHAT_SCREEN", "Chat screen"
    CHAT_EXPIRED = "CHAT_EXPIRED", "Chat expired"
    STORE = "STORE", "Store"


class CoinType(models.TextChoices):
    """Single unified wallet currency. One Coin is spent on any paid action
    (reveal, safe reveal, extend) at its fixed coin cost, and is sold in the store
    as coin packs. (Historical ledger rows may still carry the retired REVEAL /
    SAFE_REVEAL values; only COIN is written going forward.)"""

    COIN = "COIN", "Coin"


class CoinLedgerReason(models.TextChoices):
    BUNDLE_PURCHASE = "BUNDLE_PURCHASE", "Coin pack purchase"
    CANCELLATION_CREDIT = "CANCELLATION_CREDIT", "Cancellation credit"
    ACTION_CONSUME = "ACTION_CONSUME", "Action consume"
    ADMIN_ADJUST = "ADMIN_ADJUST", "Admin adjust"
