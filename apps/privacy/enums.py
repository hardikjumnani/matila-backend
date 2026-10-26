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
    NON_LATIN = "NON_LATIN", "Non-English script"


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
    """Non-blocking soft signals from the second-hand Veil (SuspicionGuard).

    Classed (see apps.privacy.suspicion_data.SIGNAL_CLASS). Ambient signals are
    normal for this user base and are excluded from the priority (ranking/tier)
    score. The legacy OBFUSCATION / NEAR_MISS members are kept so historical rows
    still validate; the scanner now emits the granular signals below."""

    # ambient
    NON_LATIN_SCRIPT = "NON_LATIN_SCRIPT", "Non-Latin script"
    ROMANIZED_INDIC = "ROMANIZED_INDIC", "Romanized Indic / code-mix"
    GIBBERISH = "GIBBERISH", "Gibberish / keyboard-mash"
    # structural
    OBFUSCATION_INVISIBLE = "OBFUSCATION_INVISIBLE", "Invisible / confusable chars"
    OBFUSCATION_SPLIT = "OBFUSCATION_SPLIT", "Separator-split / spaced letters"
    OBFUSCATION_LEET = "OBFUSCATION_LEET", "Heavy leet substitution"
    # pii (sub-threshold leak tells)
    NEAR_PHONE = "NEAR_PHONE", "Near-phone digit run"
    PARTIAL_DIGITS = "PARTIAL_DIGITS", "Partial spelled digits"
    DIGIT_DENSITY = "DIGIT_DENSITY", "High digit density"
    BRAND_MENTION = "BRAND_MENTION", "Platform / brand mention"
    HANDLE_SOFT = "HANDLE_SOFT", "Letters-only handle after platform"
    SELFNAME_SOFT = "SELFNAME_SOFT", "Sub-threshold self-name"
    REVERSAL_HINT = "REVERSAL_HINT", "Reversal cue / reversed brand"
    CONTACT_SOFT = "CONTACT_SOFT", "Contact-intent phrase (no platform)"
    ENTROPY_TOKEN = "ENTROPY_TOKEN", "High-entropy token"
    # behavioral (cross-message / cadence)
    DIGIT_DRIP = "DIGIT_DRIP", "Digit-per-message drip cadence"
    CHAR_BURST = "CHAR_BURST", "Single-character message burst"
    CROSS_MESSAGE = "CROSS_MESSAGE", "Cross-message near-leak assembly"
    BLOCKED_LEAK = "BLOCKED_LEAK", "Veil hard-block (recorded)"
    # legacy (kept for historical-row validity; no longer emitted)
    OBFUSCATION = "OBFUSCATION", "Obfuscation (legacy)"
    NEAR_MISS = "NEAR_MISS", "Near-miss (legacy)"


class SuspicionTier(models.TextChoices):
    """Admin-review PRIORITY label derived from a user's decayed priority score.
    A review label only: it never blocks, masks, notifies, or acts on the account.
    """

    CLEAN = "CLEAN", "Clean"
    WATCH = "WATCH", "Watch"
    ELEVATED = "ELEVATED", "Elevated"
    HIGH = "HIGH", "High"


class SuspicionReviewStatus(models.TextChoices):
    """Admin assessment state of a user's accumulated suspicion."""

    UNREVIEWED = "UNREVIEWED", "Unreviewed"
    REVIEWED = "REVIEWED", "Reviewed"
    CLEARED = "CLEARED", "Cleared (benign)"
    ACTIONED = "ACTIONED", "Actioned"
