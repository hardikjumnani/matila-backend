"""Enumerations owned by the Veil privacy / anti-leakage engine.

See ``docs/VEIL_ENGINE_PLAN.md``. Actions are deliberately exactly
ALLOW / BLOCK / ESCALATE — there is no WARN-and-deliver or MASK tier: a flagged
message is allowed whole or blocked whole, and enforcement is strict from the
first attempt (only the *tone* of the block message graduates).
"""

from __future__ import annotations

from django.db import models


class LeakCategory(models.TextChoices):
    PHONE = "PHONE", "Phone number"
    EMAIL = "EMAIL", "Email"
    UPI = "UPI", "UPI / payment handle"
    URL = "URL", "Link"
    SOCIAL_HANDLE = "SOCIAL_HANDLE", "Social handle"
    PLATFORM = "PLATFORM", "Platform mention"
    STEERING = "STEERING", "Off-app steering"
    SOLICITATION = "SOLICITATION", "Soliciting contact"
    MEETING = "MEETING", "Offline meeting coordination"
    SELF_NAME = "SELF_NAME", "Self-identifying name"


class LeakSeverity(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"


class LeakAction(models.TextChoices):
    ALLOW = "ALLOW", "Allow"
    BLOCK = "BLOCK", "Block"
    ESCALATE = "ESCALATE", "Escalate"


class VeilMode(models.TextChoices):
    SHADOW = "shadow", "Shadow (log only)"
    ENFORCE = "enforce", "Enforce"


class ProfanityTier(models.TextChoices):
    """Muffle severity tiers. T0 is left untouched; T1/T2 are masked; T2 is also
    flagged for review. See docs/MUFFLE_PROFANITY_PLAN.md."""

    T0_CASUAL = "T0_CASUAL", "Casual (allowed)"
    T1_HARSH = "T1_HARSH", "Harsh / targeted"
    T2_SLUR = "T2_SLUR", "Slur / hate"


class MuffleMode(models.TextChoices):
    SHADOW = "shadow", "Shadow (log only)"
    MASK = "mask", "Mask"


class ViolationSource(models.TextChoices):
    """Where a recorded violation was caught. BACKEND = the Veil scanner on the
    server; FRONTEND = the app's own client-side guard, self-reported."""

    BACKEND = "BACKEND", "Backend (Veil)"
    FRONTEND = "FRONTEND", "Frontend (client-reported)"


class SuspicionSignal(models.TextChoices):
    """Non-blocking soft signals from the second-hand Veil (SuspicionGuard)."""

    NON_LATIN_SCRIPT = "NON_LATIN_SCRIPT", "Non-Latin script"
    ROMANIZED_INDIC = "ROMANIZED_INDIC", "Romanized Indic / code-mix"
    GIBBERISH = "GIBBERISH", "Gibberish / keyboard-mash"
    OBFUSCATION = "OBFUSCATION", "Obfuscation / evasion characters"
    NEAR_MISS = "NEAR_MISS", "Near-miss leak signal"


class SuspicionReviewStatus(models.TextChoices):
    """Admin assessment state of a user's accumulated suspicion."""

    UNREVIEWED = "UNREVIEWED", "Unreviewed"
    REVIEWED = "REVIEWED", "Reviewed"
    CLEARED = "CLEARED", "Cleared (benign)"
    ACTIONED = "ACTIONED", "Actioned"
