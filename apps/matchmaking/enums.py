"""Enumerations owned by the matchmaking domain."""

from __future__ import annotations

from django.db import models


class MatchQueueStatus(models.TextChoices):
    SEARCHING = "SEARCHING", "Searching"
    CANCELLED = "CANCELLED", "Cancelled"
    TIMEOUT = "TIMEOUT", "Timeout"
