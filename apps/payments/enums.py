"""Enumerations owned by the payments domain."""

from __future__ import annotations

from django.db import models


class PaymentPurpose(models.TextChoices):
    REVEAL = "REVEAL", "Reveal"
    CHAT_EXTENSION = "CHAT_EXTENSION", "Chat extension"


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
