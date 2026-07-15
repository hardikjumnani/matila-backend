"""Enumerations owned by the reveal domain."""

from __future__ import annotations

from django.db import models


class RevealIntentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"


class RevealTriggerType(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    CHAT_EXPIRED = "CHAT_EXPIRED", "Chat expired"
