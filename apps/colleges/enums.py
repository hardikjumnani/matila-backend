"""Enumerations owned by the colleges domain."""

from __future__ import annotations

from django.db import models


class LaunchMilestone(models.TextChoices):
    """College-wide scheduled launch-countdown notifications (idempotent per
    college via LaunchNotification). The per-user 'approved' message is sent
    inline on approval, not tracked here."""

    T_MINUS_7D = "T_MINUS_7D", "7 days before launch"
    T_MINUS_1D = "T_MINUS_1D", "1 day before launch"
    T_MINUS_1H = "T_MINUS_1H", "1 hour before launch"
    LAUNCH = "LAUNCH", "Launched"
