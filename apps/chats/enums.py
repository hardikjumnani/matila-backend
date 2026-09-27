"""Enumerations owned by the chats domain."""

from __future__ import annotations

from django.db import models


class ChatStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    EXTENDED = "EXTENDED", "Extended"
    REVEALED = "REVEALED", "Revealed"
    EXPIRED = "EXPIRED", "Expired"
    ENDED = "ENDED", "Ended"


class ChatPhase(models.TextChoices):
    """Frozen phase set. There is deliberately no POST_EXPIRY phase: on expiry
    the status becomes EXPIRED while the phase remains ANONYMOUS (identity was
    never revealed). See DATABASE_SCHEMA.md (source of truth)."""

    ANONYMOUS = "ANONYMOUS", "Anonymous"
    REVEALED = "REVEALED", "Revealed"


class EndReason(models.TextChoices):
    EXPIRED = "EXPIRED", "Expired"
    USER_EXIT = "USER_EXIT", "User exit"
    AUTO_EXIT = "AUTO_EXIT", "Auto exit"
    SAFE_REJECT = "SAFE_REJECT", "Safe reveal rejected"
    REPORT = "REPORT", "Report"
    REVEAL = "REVEAL", "Reveal"
    SYSTEM = "SYSTEM", "System"


class ParticipantStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    LEFT = "LEFT", "Left"


class JoinedVia(models.TextChoices):
    MATCH = "MATCH", "Match"
