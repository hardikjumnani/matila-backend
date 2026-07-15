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
from apps.users.enums import AccountStatus, NextAction, VerificationStatus
from apps.users.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SessionData:
    """Result payload of a successful session bootstrap."""

    user: User
    next_action: NextAction
    created: bool


class AuthService:
    """Authentication, user bootstrap, and profile management (owns users)."""

    def __init__(self, *, storage_service=None) -> None:
        self._storage_service = storage_service

    @property
    def _storage(self):
        # Lazily construct the storage service so auth-only usage never imports
        # boto3.
        if self._storage_service is None:
            from apps.common.services.storage_service import StorageService

            self._storage_service = StorageService()
        return self._storage_service

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
    ) -> ServiceResult[User]:
        """Update editable profile fields.

        Gender becomes immutable once verification is approved (frozen rule);
        college email is never editable through the API.
        """
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

        if update_fields:
            update_fields.append("updated_at")
            user.save(update_fields=update_fields)
        return ServiceResult.ok(user)

    def complete_onboarding(self, user: User) -> ServiceResult[User]:
        """Mark onboarding complete once required profile fields are present."""
        missing = [
            name
            for name, value in (
                ("full_name", user.full_name),
                ("gender", user.gender),
                ("intent", user.intent),
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
            user = User.objects.create(
                firebase_uid=firebase_uid,
                college_email=email,
            )
            created = True
            logger.info("Bootstrapped new user %s", user.id)

        status_error = self._account_status_error(user)
        if status_error is not None:
            return status_error

        user.last_active_at = timezone.now()
        user.save(update_fields=["last_active_at", "updated_at"])

        next_action = self._determine_next_action(user)
        return ServiceResult.ok(
            SessionData(user=user, next_action=next_action, created=created)
        )

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
            return NextAction.GO_HOME

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
