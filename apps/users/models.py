"""
User domain models.

``User`` is the application's domain identity for an authenticated college
student. It is intentionally NOT Django's ``AUTH_USER_MODEL``: authentication is
performed by Firebase, and this model carries no password or staff flags. The
Django admin continues to use the default ``auth.User`` for internal operators.

Onboarding is progressive — a row is created at first authenticated session
bootstrap with only ``firebase_uid`` and ``college_email`` populated; profile
fields are filled during onboarding. Nullable/blank fields below reflect that
lifecycle rather than optionality of the final profile.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import TimeStampedUUIDModel

from .enums import AccountStatus, Gender, Intent, VerificationStatus


class User(TimeStampedUUIDModel):
    # --- Identity (immutable anchors set at session bootstrap) --------------
    firebase_uid = models.CharField(max_length=128, unique=True)
    college_email = models.EmailField(unique=True)

    # --- Profile (collected during onboarding) ------------------------------
    full_name = models.CharField(max_length=150, blank=True, default="")
    profile_photo_url = models.URLField(max_length=512, blank=True, default="")
    gender = models.CharField(
        max_length=10, choices=Gender.choices, blank=True, default=""
    )
    intent = models.CharField(
        max_length=20, choices=Intent.choices, blank=True, default=""
    )
    # Multi-select: a JSON list of Gender values the user is willing to match
    # with. Matching (MatchmakingService) requires mutual compatibility.
    gender_preferences = models.JSONField(default=list, blank=True)

    # --- Verification -------------------------------------------------------
    verification_status = models.CharField(
        max_length=25,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    # --- Account lifecycle --------------------------------------------------
    account_status = models.CharField(
        max_length=10,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
    )
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    last_active_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "users"
        indexes = [
            # Admin verification queue is filtered by verification_status.
            models.Index(fields=["verification_status"], name="idx_user_verif_status"),
            models.Index(fields=["account_status"], name="idx_user_account_status"),
        ]

    def __str__(self) -> str:
        return f"User<{self.id}> {self.college_email}"

    # --- DRF / Channels compatibility --------------------------------------
    # This is a Firebase-authenticated domain model, not a Django auth user, so
    # it must expose the identity markers DRF permissions and Channels rely on.
    # A resolved User instance always represents an authenticated identity.
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False
