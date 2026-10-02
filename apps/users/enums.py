"""
Enumerations owned by the users domain.

``Gender`` and ``Intent`` are also consumed by the matchmaking domain (the
match queue denormalizes them for filtering). They live here because the users
domain owns user identity; matchmaking depends on users, so importing from here
introduces no dependency cycle.
"""

from __future__ import annotations

import enum

from django.db import models


class NextAction(str, enum.Enum):
    """Navigation hint returned by session bootstrap to guide the Flutter client.

    Not a database value — it is derived on the fly from the user's onboarding
    and verification state, so it is a plain string enum rather than a model
    ``TextChoices``.
    """

    COMPLETE_ONBOARDING = "COMPLETE_ONBOARDING"
    SUBMIT_VERIFICATION = "SUBMIT_VERIFICATION"
    WAIT_FOR_VERIFICATION = "WAIT_FOR_VERIFICATION"
    GO_HOME = "GO_HOME"


class Gender(models.TextChoices):
    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"
    OTHER = "OTHER", "Other"


class Intent(models.TextChoices):
    RELATIONSHIP = "RELATIONSHIP", "Relationship"
    FRIENDSHIP = "FRIENDSHIP", "Friendship"
    CASUAL = "CASUAL", "Casual"


class VerificationStatus(models.TextChoices):
    """Shared by ``users.verification_status`` and ``verification_requests.status``."""

    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    RESUBMISSION_REQUIRED = "RESUBMISSION_REQUIRED", "Resubmission required"


class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspended"
    BANNED = "BANNED", "Banned"
    DELETED = "DELETED", "Deleted"
