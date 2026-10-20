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


def _default_college_id():
    """FK default for ``User.college``: the catch-all 'Unassigned' college.

    Keeps the column NOT NULL for any create that omits a college (tests,
    legacy rows via AddField). Real sign-ups set the resolved college explicitly
    in the auth bootstrap, so this default is only a safety net.
    """
    from datetime import datetime, timezone as _tz

    from apps.colleges.models import College

    return College.objects.get_or_create(
        code="UNASSIGNED",
        defaults={
            "name": "Unassigned",
            "allowed_email_domains": [],
            "is_active": False,
            # Launched "since forever" so the catch-all never imposes the launch
            # gate on legacy/seed/test accounts parked here. Real sign-ups resolve
            # to a real college and never land on Unassigned.
            "launch_date": datetime(2000, 1, 1, tzinfo=_tz.utc),
        },
    )[0].pk


class User(TimeStampedUUIDModel):
    # --- Identity (immutable anchors set at session bootstrap) --------------
    firebase_uid = models.CharField(max_length=128, unique=True)
    college_email = models.EmailField(unique=True)

    # Every user belongs to exactly one college, resolved from their verified
    # email domain at sign-up (unknown domains are rejected by the bootstrap).
    # NOT NULL: the callable default parks any create that omits it on the
    # catch-all "Unassigned" college, so the column is never null. PROTECT:
    # colleges are never deleted out from under their members.
    college = models.ForeignKey(
        "colleges.College",
        on_delete=models.PROTECT,
        related_name="users",
        default=_default_college_id,
    )

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
    # Date of birth, captured once at onboarding (set-once; not editable after).
    # Nullable: pre-feature users have none, and such users are simply excluded
    # by any active age filter (age cannot be verified). Age is derived, never
    # stored. See the ``age`` property below and the matchmaking age filter.
    date_of_birth = models.DateField(null=True, blank=True)

    # --- Age preference (relationship-intent hard filter) -------------------
    # Off by default ("all ages"). When enabled on a RELATIONSHIP user, matching
    # restricts partners to [age_preference_min, age_preference_max] inclusive.
    # Stored regardless of intent but applied only for relationship intent.
    age_preference_enabled = models.BooleanField(default=False)
    age_preference_min = models.PositiveSmallIntegerField(null=True, blank=True)
    age_preference_max = models.PositiveSmallIntegerField(null=True, blank=True)

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
        # "<name>--<id>": full_name when set, else college_email (users are blank
        # pre-onboarding) so the label is never just "--<id>".
        return f"{self.full_name or self.college_email}--{self.id}"

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

    @property
    def age(self) -> int | None:
        """Current age in whole years from ``date_of_birth``, or None if unset.

        Derived (never stored) so it stays correct as time passes. Accounts for
        whether this year's birthday has occurred yet.
        """
        if self.date_of_birth is None:
            return None
        from django.utils import timezone

        today = timezone.now().date()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
