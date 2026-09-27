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
    RAZORPAY = "RAZORPAY", "Razorpay"
    GOOGLE_PLAY = "GOOGLE_PLAY", "Google Play"


class PaymentInitiatedFrom(models.TextChoices):
    CHAT_SCREEN = "CHAT_SCREEN", "Chat screen"
    CHAT_EXPIRED = "CHAT_EXPIRED", "Chat expired"
    STORE = "STORE", "Store"


class CoinType(models.TextChoices):
    """Wallet currencies. REVEAL coins are sold in the store and spent on a
    standard-reveal side (or the boy's safe-reveal side). SAFE_REVEAL coins are
    girl-only, never sold, and spent on the girl's safe-reveal side."""

    REVEAL = "REVEAL", "Reveal coin"
    SAFE_REVEAL = "SAFE_REVEAL", "Safe reveal coin"


class CoinLedgerReason(models.TextChoices):
    BUNDLE_PURCHASE = "BUNDLE_PURCHASE", "Bundle purchase"
    CANCELLATION_CREDIT = "CANCELLATION_CREDIT", "Cancellation credit"
    REVEAL_CONSUME = "REVEAL_CONSUME", "Reveal consume"
    ADMIN_ADJUST = "ADMIN_ADJUST", "Admin adjust"
