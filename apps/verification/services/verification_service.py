"""
Verification service.

Owns ``verification_requests`` and updates ``users.verification_status``.

An in-progress attempt is a "draft": a ``verification_requests`` row with
``submitted_at IS NULL``. Gesture assignment and document uploads populate the
draft; submission finalizes it. Every submission is preserved — a resubmission
creates a new attempt rather than mutating a prior one.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, BinaryIO

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.enums import ActorType
from apps.common.results import ServiceResult
from apps.users.enums import VerificationStatus
from apps.users.models import User
from apps.verification.models import VerificationRequest

logger = logging.getLogger(__name__)

_COLLEGE_ID_PREFIX = "verification/college-id"
_GESTURE_SELFIE_PREFIX = "verification/gesture-selfie"


class VerificationService:
    """Identity-verification workflow and admin review."""

    def __init__(
        self,
        *,
        configuration_service=None,
        storage_service=None,
        notification_service=None,
        audit_service=None,
    ) -> None:
        if configuration_service is None:
            from apps.configuration.services.configuration_service import (
                ConfigurationService,
            )

            configuration_service = ConfigurationService()
        if storage_service is None:
            from apps.common.services.storage_service import StorageService

            storage_service = StorageService()
        if notification_service is None:
            from apps.notifications.services.notification_service import (
                NotificationService,
            )

            notification_service = NotificationService()
        if audit_service is None:
            from apps.audit.services.audit_service import AuditService

            audit_service = AuditService()
        self._config = configuration_service
        self._storage = storage_service
        self._notifications = notification_service
        self._audit = audit_service

    # -- Queries ------------------------------------------------------------

    def get_latest_request(self, user: User) -> VerificationRequest | None:
        return (
            VerificationRequest.objects.filter(user=user)
            .order_by("-attempt_number")
            .first()
        )

    def get_history(self, user: User):
        return VerificationRequest.objects.filter(user=user).order_by("-attempt_number")

    def has_submitted_request(self, user: User) -> bool:
        """Whether the user has ever submitted a request for review."""
        return VerificationRequest.objects.filter(
            user=user, submitted_at__isnull=False
        ).exists()

    def get_status(self, user: User) -> dict[str, Any]:
        return {
            "verification_status": user.verification_status,
            "latest_request": self.get_latest_request(user),
        }

    # -- Draft / attempt management ----------------------------------------

    def _active_draft(self, user: User) -> VerificationRequest | None:
        return (
            VerificationRequest.objects.filter(user=user, submitted_at__isnull=True)
            .order_by("-attempt_number")
            .first()
        )

    @transaction.atomic
    def _get_or_create_draft(self, user: User) -> ServiceResult[VerificationRequest]:
        """Return the user's current draft attempt, creating one if needed.

        Denies starting a new attempt once the user is already verified.
        """
        if user.verification_status == VerificationStatus.APPROVED:
            return ServiceResult.fail("CONFLICT", "Your account is already verified.")
        draft = self._active_draft(user)
        if draft is not None:
            return ServiceResult.ok(draft)

        next_attempt = (
            VerificationRequest.objects.filter(user=user).aggregate(
                m=Max("attempt_number")
            )["m"]
            or 0
        ) + 1
        draft = VerificationRequest.objects.create(
            user=user, attempt_number=next_attempt
        )
        return ServiceResult.ok(draft)

    def generate_gesture(self, user: User) -> ServiceResult[str]:
        """Assign a random gesture instruction to the user's draft attempt."""
        pool = self._config.get_gesture_pool()
        if not pool:
            return ServiceResult.fail(
                "INTERNAL_SERVER_ERROR", "No gesture pool is configured."
            )
        draft_result = self._get_or_create_draft(user)
        if draft_result.failed:
            return ServiceResult.fail(
                draft_result.error_code, draft_result.error_message
            )
        draft = draft_result.data
        # secrets.choice: unpredictable selection so the gesture cannot be
        # anticipated and pre-recorded before it is requested.
        gesture = secrets.choice(pool)
        draft.gesture_type = gesture
        draft.save(update_fields=["gesture_type", "updated_at"])
        return ServiceResult.ok(gesture)

    def upload_college_id(
        self, user: User, *, fileobj: BinaryIO, filename: str, content_type: str
    ) -> ServiceResult[VerificationRequest]:
        return self._upload_document(
            user,
            fileobj=fileobj,
            filename=filename,
            content_type=content_type,
            prefix=_COLLEGE_ID_PREFIX,
            field="college_id_image_url",
        )

    def upload_gesture_selfie(
        self, user: User, *, fileobj: BinaryIO, filename: str, content_type: str
    ) -> ServiceResult[VerificationRequest]:
        return self._upload_document(
            user,
            fileobj=fileobj,
            filename=filename,
            content_type=content_type,
            prefix=_GESTURE_SELFIE_PREFIX,
            field="gesture_selfie_image_url",
        )

    def _upload_document(
        self,
        user: User,
        *,
        fileobj: BinaryIO,
        filename: str,
        content_type: str,
        prefix: str,
        field: str,
    ) -> ServiceResult[VerificationRequest]:
        draft_result = self._get_or_create_draft(user)
        if draft_result.failed:
            return draft_result
        draft = draft_result.data
        key = self._storage.build_key(prefix, filename)
        self._storage.upload_fileobj(fileobj, key, content_type=content_type)
        setattr(draft, field, key)
        draft.save(update_fields=[field, "updated_at"])
        return ServiceResult.ok(draft)

    @transaction.atomic
    def submit(self, user: User) -> ServiceResult[VerificationRequest]:
        """Finalize the draft attempt and place it in the review queue."""
        if user.verification_status == VerificationStatus.APPROVED:
            return ServiceResult.fail("CONFLICT", "Your account is already verified.")

        draft = (
            VerificationRequest.objects.select_for_update()
            .filter(user=user, submitted_at__isnull=True)
            .order_by("-attempt_number")
            .first()
        )
        if draft is None:
            return ServiceResult.fail(
                "VALIDATION_ERROR", "No verification attempt in progress."
            )
        missing = [
            name
            for name, value in (
                ("college ID", draft.college_id_image_url),
                ("gesture selfie", draft.gesture_selfie_image_url),
                ("gesture", draft.gesture_type),
            )
            if not value
        ]
        if missing:
            return ServiceResult.fail(
                "VALIDATION_ERROR",
                f"Verification is incomplete: missing {', '.join(missing)}.",
            )

        now = timezone.now()
        draft.submitted_at = now
        draft.status = VerificationStatus.PENDING
        draft.save(update_fields=["submitted_at", "status", "updated_at"])

        user.verification_status = VerificationStatus.PENDING
        user.save(update_fields=["verification_status", "updated_at"])
        logger.info("Verification request %s submitted by user %s", draft.id, user.id)
        return ServiceResult.ok(draft)

    # -- Admin review -------------------------------------------------------

    def approve(
        self,
        *,
        request_id: str,
        reviewed_by=None,
        admin_id: str = "",
        notes: str = "",
    ) -> ServiceResult[VerificationRequest]:
        return self._review(
            request_id=request_id,
            new_status=VerificationStatus.APPROVED,
            reviewed_by=reviewed_by,
            admin_id=admin_id,
            notes=notes,
            notification_type="verification.approved",
            notification_title="You're verified!",
            notification_body="Your identity verification was approved.",
            audit_action="verification.approved",
        )

    def reject(
        self,
        *,
        request_id: str,
        reviewed_by=None,
        admin_id: str = "",
        notes: str = "",
    ) -> ServiceResult[VerificationRequest]:
        return self._review(
            request_id=request_id,
            new_status=VerificationStatus.REJECTED,
            reviewed_by=reviewed_by,
            admin_id=admin_id,
            notes=notes,
            notification_type="verification.rejected",
            notification_title="Verification rejected",
            notification_body="Your verification could not be approved.",
            audit_action="verification.rejected",
        )

    def request_resubmission(
        self,
        *,
        request_id: str,
        reviewed_by=None,
        admin_id: str = "",
        notes: str = "",
    ) -> ServiceResult[VerificationRequest]:
        return self._review(
            request_id=request_id,
            new_status=VerificationStatus.RESUBMISSION_REQUIRED,
            reviewed_by=reviewed_by,
            admin_id=admin_id,
            notes=notes,
            notification_type="verification.resubmission_required",
            notification_title="Please resubmit your verification",
            notification_body="We need you to resubmit your verification.",
            audit_action="verification.resubmission_required",
        )

    def _review(
        self,
        *,
        request_id: str,
        new_status: str,
        reviewed_by,
        admin_id: str,
        notes: str,
        notification_type: str,
        notification_title: str,
        notification_body: str,
        audit_action: str,
    ) -> ServiceResult[VerificationRequest]:
        with transaction.atomic():
            request = (
                VerificationRequest.objects.select_for_update()
                .select_related("user")
                .filter(id=request_id)
                .first()
            )
            if request is None:
                return ServiceResult.fail(
                    "RESOURCE_NOT_FOUND", "Verification request not found."
                )
            if request.submitted_at is None:
                return ServiceResult.fail(
                    "VALIDATION_ERROR",
                    "This verification request has not been submitted.",
                )

            now = timezone.now()
            request.status = new_status
            request.review_notes = notes
            request.reviewed_by = reviewed_by
            request.reviewed_at = now
            request.save(
                update_fields=[
                    "status",
                    "review_notes",
                    "reviewed_by",
                    "reviewed_at",
                    "updated_at",
                ]
            )

            user = request.user
            user.verification_status = new_status
            update_fields = ["verification_status", "updated_at"]
            if new_status == VerificationStatus.APPROVED:
                user.verified_at = now
                update_fields.append("verified_at")
            user.save(update_fields=update_fields)

        # Side effects run after the transaction commits.
        self._audit.log(
            actor_type=ActorType.ADMIN,
            actor_id=admin_id,
            action=audit_action,
            entity_type="verification_request",
            entity_id=str(request.id),
            metadata={"user_id": str(user.id), "status": new_status},
        )
        self._notifications.create_notification(
            user=user,
            type=notification_type,
            title=notification_title,
            body=notification_body,
        )
        logger.info("Verification request %s -> %s", request.id, new_status)
        return ServiceResult.ok(request)
