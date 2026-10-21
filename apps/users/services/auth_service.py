"""
Authentication and user-bootstrap service.

Owns the ``users`` table. Responsible for resolving Firebase-authenticated
users, creating first-time users during session bootstrap, validating account
status, and deriving the client's next navigation action.

This service is framework-agnostic: it returns ``ServiceResult`` / raises domain
exceptions and never imports DRF or Channels. The authentication class and the
WebSocket middleware translate its outcomes into transport-specific responses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.common.results import ServiceResult
from apps.users.constants import MAX_AGE, MIN_AGE
from apps.users.enums import AccountStatus, NextAction, VerificationStatus
from apps.users.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SessionData:
    """Result payload of a successful session bootstrap."""

    user: User
    next_action: NextAction
    created: bool
    # Admin's resubmission note, surfaced on the re-onboarding entry so the user
    # knows why. Non-empty only when verification_status is RESUBMISSION_REQUIRED.
    review_notes: str = ""


class AuthService:
    """Authentication, user bootstrap, and profile management (owns users)."""

    def __init__(self, *, storage_service=None, audit_service=None) -> None:
        self._storage_service = storage_service
        self._audit_service = audit_service

    @property
    def _storage(self):
        # Lazily construct the storage service so auth-only usage never imports
        # the Azure SDK.
        if self._storage_service is None:
            from apps.common.services.storage_service import StorageService

            self._storage_service = StorageService()
        return self._storage_service

    @property
    def _audit(self):
        if self._audit_service is None:
            from apps.audit.services.audit_service import AuditService

            self._audit_service = AuditService()
        return self._audit_service

    def update_account_status(
        self, *, user: User, status: str, admin_id: str
    ) -> ServiceResult[User]:
        """Admin action: change a user's account status and audit it."""
        from apps.audit.enums import ActorType

        if status not in AccountStatus.values:
            return ServiceResult.fail("VALIDATION_ERROR", "Invalid account status.")
        user.account_status = status
        user.save(update_fields=["account_status", "updated_at"])
        self._audit.log(
            actor_type=ActorType.ADMIN,
            actor_id=admin_id,
            action=f"user.status.{status.lower()}",
            entity_type="user",
            entity_id=str(user.id),
            metadata={"account_status": status},
        )
        return ServiceResult.ok(user)

    def get_user_by_firebase_uid(self, firebase_uid: str) -> User | None:
        """Return the user for a Firebase UID, or ``None`` if not bootstrapped."""
        if not firebase_uid:
            return None
        return User.objects.filter(firebase_uid=firebase_uid).first()

    # -- Profile management -------------------------------------------------

    def update_profile(
        self,
        user: User,
        *,
        full_name: str | None = None,
        gender: str | None = None,
        intent: str | None = None,
        gender_preferences: list[str] | None = None,
        date_of_birth=None,
        age_preference_enabled: bool | None = None,
        age_preference_min: int | None = None,
        age_preference_max: int | None = None,
    ) -> ServiceResult[User]:
        """Update editable profile fields.

        Gender becomes immutable once verification is approved (frozen rule);
        college email is never editable through the API. Date of birth is set
        once at onboarding (not editable after). Age preference is a
        relationship-intent matching filter; see the matchmaking service.
        """
        # Pre-launch lock: once a user has onboarded, the app is countdown-only
        # until their college launches — no profile edits. (Initial onboarding,
        # while onboarding_completed_at is None, is still allowed.)
        if user.onboarding_completed_at is not None:
            from apps.colleges.services.college_service import CollegeService

            if not CollegeService().is_user_launched(user):
                return ServiceResult.fail(
                    "COLLEGE_NOT_LAUNCHED",
                    "Profile changes are locked until your college launches.",
                )
        update_fields: list[str] = []
        if full_name is not None:
            user.full_name = full_name
            update_fields.append("full_name")
        if gender is not None:
            if user.verification_status == VerificationStatus.APPROVED:
                return ServiceResult.fail(
                    "CONFLICT", "Gender cannot be changed after verification."
                )
            user.gender = gender
            update_fields.append("gender")
        if intent is not None:
            user.intent = intent
            update_fields.append("intent")
        if gender_preferences is not None:
            user.gender_preferences = gender_preferences
            update_fields.append("gender_preferences")

        if date_of_birth is not None:
            # Set-once: DOB is captured at onboarding and never changed via the API
            # afterward (protects the age-filter integrity; admins can correct).
            if user.onboarding_completed_at is not None:
                return ServiceResult.fail(
                    "CONFLICT", "Date of birth cannot be changed after onboarding."
                )
            dob_error = self._dob_error(date_of_birth)
            if dob_error is not None:
                return ServiceResult.fail("VALIDATION_ERROR", dob_error)
            user.date_of_birth = date_of_birth
            update_fields.append("date_of_birth")

        if (
            age_preference_enabled is not None
            or age_preference_min is not None
            or age_preference_max is not None
        ):
            pref_error = self._apply_age_preference(
                user,
                enabled=age_preference_enabled,
                lo=age_preference_min,
                hi=age_preference_max,
                update_fields=update_fields,
            )
            if pref_error is not None:
                return ServiceResult.fail("VALIDATION_ERROR", pref_error)

        if update_fields:
            update_fields.append("updated_at")
            user.save(update_fields=update_fields)
        return ServiceResult.ok(user)

    @staticmethod
    def _dob_error(dob) -> str | None:
        """Validate a date of birth: not in the future and at least MIN_AGE.

        Returns an error message, or None when valid.
        """
        today = timezone.now().date()
        if dob > today:
            return "Date of birth cannot be in the future."
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < MIN_AGE:
            return f"You must be at least {MIN_AGE} years old to use Matila."
        return None

    @staticmethod
    def _apply_age_preference(
        user: User,
        *,
        enabled: bool | None,
        lo: int | None,
        hi: int | None,
        update_fields: list[str],
    ) -> str | None:
        """Merge the incoming age-preference fields onto the user and validate the
        effective state. Returns an error message, or None when applied.

        Disabling keeps the stored range so re-enabling restores it. When the
        effective state is enabled, both bounds must be present, ordered, and in
        range.
        """
        eff_enabled = enabled if enabled is not None else user.age_preference_enabled
        eff_lo = lo if lo is not None else user.age_preference_min
        eff_hi = hi if hi is not None else user.age_preference_max

        if eff_enabled:
            if eff_lo is None or eff_hi is None:
                return "An age preference needs both a minimum and a maximum age."
            if not (MIN_AGE <= eff_lo <= MAX_AGE and MIN_AGE <= eff_hi <= MAX_AGE):
                return f"Age preference must be within {MIN_AGE} and {MAX_AGE}."
            if eff_lo > eff_hi:
                return "age_preference_min must be <= age_preference_max."

        if enabled is not None:
            user.age_preference_enabled = enabled
            update_fields.append("age_preference_enabled")
        if lo is not None:
            user.age_preference_min = lo
            update_fields.append("age_preference_min")
        if hi is not None:
            user.age_preference_max = hi
            update_fields.append("age_preference_max")
        return None

    def complete_onboarding(self, user: User) -> ServiceResult[User]:
        """Mark onboarding complete once required profile fields are present."""
        missing = [
            name
            for name, value in (
                ("full_name", user.full_name),
                ("gender", user.gender),
                ("intent", user.intent),
                ("date_of_birth", user.date_of_birth),
            )
            if not value
        ]
        if not user.gender_preferences:
            missing.append("gender_preferences")
        if missing:
            return ServiceResult.fail(
                "VALIDATION_ERROR",
                f"Onboarding is incomplete: missing {', '.join(missing)}.",
            )
        # Defensive: a DOB present on the row must still satisfy the age floor.
        if user.date_of_birth is not None:
            dob_error = self._dob_error(user.date_of_birth)
            if dob_error is not None:
                return ServiceResult.fail("VALIDATION_ERROR", dob_error)

        if user.onboarding_completed_at is None:
            user.onboarding_completed_at = timezone.now()
            user.save(update_fields=["onboarding_completed_at", "updated_at"])
        return ServiceResult.ok(user)

    def upload_profile_photo(
        self, user: User, *, fileobj, filename: str, content_type: str
    ) -> ServiceResult[User]:
        """Store a profile photo and record its storage key on the user."""
        key = self._storage.build_key("profile-photos", filename)
        self._storage.upload_fileobj(fileobj, key, content_type=content_type)
        user.profile_photo_url = key
        user.save(update_fields=["profile_photo_url", "updated_at"])
        return ServiceResult.ok(user)

    @transaction.atomic
    def bootstrap_session(
        self, *, firebase_uid: str, email: str
    ) -> ServiceResult[SessionData]:
        """Resolve or create the user for a verified Firebase identity.

        Creates a first-time user with only the immutable identity anchors set;
        profile fields are populated later during onboarding. Denies access to
        non-active accounts. Refreshes ``last_active_at`` and derives the client
        ``next_action``.
        """
        if not firebase_uid or not email:
            return ServiceResult.fail(
                "VALIDATION_ERROR",
                "Firebase token is missing a UID or email claim.",
            )

        # Row-lock the user (if present) so concurrent bootstraps of the same
        # identity cannot race on last_active_at / creation.
        user = (
            User.objects.select_for_update().filter(firebase_uid=firebase_uid).first()
        )
        created = False
        if user is None:
            # Every user must belong to a supported college, resolved from their
            # verified email domain. Unknown domains are turned away at sign-up.
            from apps.colleges.services.college_service import CollegeService

            college = CollegeService().resolve_for_email(email)
            if college is None:
                return ServiceResult.fail(
                    "COLLEGE_NOT_SUPPORTED",
                    "Your college isn't on Matila yet.",
                )
            user = User.objects.create(
                firebase_uid=firebase_uid,
                college_email=email,
                college=college,
            )
            created = True
            logger.info("Bootstrapped new user %s (college=%s)", user.id, college.code)

        status_error = self._account_status_error(user)
        if status_error is not None:
            return status_error

        # Rejected verification is terminal: deny the session so the client
        # routes to the "not approved" screen (message carried in error.message).
        # Admin-reversible — flipping the user to RESUBMISSION_REQUIRED lets the
        # next bootstrap succeed and return SUBMIT_VERIFICATION.
        if user.verification_status == VerificationStatus.REJECTED:
            return ServiceResult.fail(
                "VERIFICATION_REJECTED", self._rejection_message(user)
            )

        user.last_active_at = timezone.now()
        user.save(update_fields=["last_active_at", "updated_at"])

        next_action = self._determine_next_action(user)
        return ServiceResult.ok(
            SessionData(
                user=user,
                next_action=next_action,
                created=created,
                review_notes=self._resubmission_note(user),
            )
        )

    def _resubmission_note(self, user: User) -> str:
        """The admin's note for a RESUBMISSION_REQUIRED user (surfaced on the
        re-onboarding entry so they know why they're resubmitting), else empty."""
        if user.verification_status != VerificationStatus.RESUBMISSION_REQUIRED:
            return ""
        from apps.verification.services.verification_service import VerificationService

        latest = VerificationService().get_latest_request(user)
        return (latest.review_notes or "").strip() if latest else ""

    def _rejection_message(self, user: User) -> str:
        """The admin's rejection note for a REJECTED user, or a generic fallback."""
        from apps.verification.services.verification_service import VerificationService

        latest = VerificationService().get_latest_request(user)
        note = (latest.review_notes or "").strip() if latest else ""
        return note or "Your verification was not approved."

    def _account_status_error(self, user: User) -> ServiceResult[SessionData] | None:
        """Return a failure result if the account may not access the app."""
        if user.account_status == AccountStatus.SUSPENDED:
            return ServiceResult.fail("ACCOUNT_SUSPENDED", "This account is suspended.")
        if user.account_status == AccountStatus.BANNED:
            return ServiceResult.fail("ACCOUNT_BANNED", "This account is banned.")
        if user.account_status == AccountStatus.DELETED:
            return ServiceResult.fail(
                "ACCOUNT_BANNED", "This account is no longer available."
            )
        return None

    def _determine_next_action(self, user: User) -> NextAction:
        """Derive the client's next navigation step from the user's state.

        COMPLETE_ONBOARDING -> SUBMIT_VERIFICATION -> WAIT_FOR_VERIFICATION -> GO_HOME
        """
        if user.onboarding_completed_at is None:
            return NextAction.COMPLETE_ONBOARDING

        if user.verification_status == VerificationStatus.APPROVED:
            # Verified, but the core app opens only at the college's launch. Until
            # then the client stays on the waiting screen, which renders a
            # countdown from the college/launched fields in the session payload.
            from apps.colleges.services.college_service import CollegeService

            if CollegeService().is_user_launched(user):
                return NextAction.GO_HOME
            return NextAction.WAIT_FOR_VERIFICATION

        if user.verification_status in (
            VerificationStatus.REJECTED,
            VerificationStatus.RESUBMISSION_REQUIRED,
        ):
            return NextAction.SUBMIT_VERIFICATION

        # PENDING: distinguish "not yet submitted" from "awaiting review" by
        # delegating to VerificationService (which owns verification_requests).
        from apps.verification.services.verification_service import (
            VerificationService,
        )

        has_submitted = VerificationService().has_submitted_request(user)
        return (
            NextAction.WAIT_FOR_VERIFICATION
            if has_submitted
            else NextAction.SUBMIT_VERIFICATION
        )
