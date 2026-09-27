"""Enumerations owned by the reveal / decision domain.

See docs/REVEAL_FLOW_SPEC.md. Supersedes the old independent RevealIntent model:
the decision phase is now a shared, server-authoritative negotiation with a
deterministic ``final_call``.
"""

from __future__ import annotations

from django.db import models


class DecisionChoice(models.TextChoices):
    REVEAL = "REVEAL", "Reveal"
    SAFE_REVEAL = "SAFE_REVEAL", "Safe reveal"
    EXTEND = "EXTEND", "Extend"
    EXIT = "EXIT", "Exit"


class FinalCall(models.TextChoices):
    REVEAL = "REVEAL", "Reveal"
    SAFE_REVEAL = "SAFE_REVEAL", "Safe reveal"
    EXTEND = "EXTEND", "Extend"
    EXIT = "EXIT", "Exit"
    REVIEW = "REVIEW", "Review"  # defensive terminal → feedback


class RevealTrigger(models.TextChoices):
    MID_CHAT = "MID_CHAT", "Mid chat"
    EXPIRY = "EXPIRY", "Expiry"


class DecisionRoundPhase(models.TextChoices):
    DECISION = "DECISION", "Decision"
    PAYMENT = "PAYMENT", "Payment"
    SAFE_DECISION = "SAFE_DECISION", "Safe reveal decision"
    RESOLVED = "RESOLVED", "Resolved"  # terminal (reveal/extend done)
    CANCELLED = "CANCELLED", "Cancelled"  # terminal (superseded/ended)


class SafeRevealDecision(models.TextChoices):
    PENDING = "PENDING", "Pending"
    REVEAL_YOURSELF = "REVEAL_YOURSELF", "Reveal yourself"
    EXIT = "EXIT", "Exit"


# Round phases past which no further decisions/payments are accepted.
TERMINAL_ROUND_PHASES = (DecisionRoundPhase.RESOLVED, DecisionRoundPhase.CANCELLED)
