"""
User data erasure (DPDP / GDPR right to erasure).

On a verified request, deletes a user's personal data — chat content and media,
profile, verification documents, device tokens, notifications, matchmaking and
reveal records, and ratings they authored — and deletes their Firebase Auth
identity so the login can never be reused.

Financial **payments** and safety **reports** are RETAINED (mandatory financial
retention / platform-safety legal basis). They reference the user row via PROTECT
foreign keys, so the row is not hard-deleted; instead it is **anonymized** — every
PII field is scrubbed — leaving those records PII-free.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.chats.models import ChatParticipant
from apps.matchmaking.models import MatchQueue
from apps.messaging.models import Message
from apps.notifications.models import DeviceToken, Notification
from apps.ratings.models import Rating
from apps.reveal.models import ParticipantDecision
from apps.users.enums import AccountStatus
from apps.users.models import User
from apps.verification.models import VerificationRequest

logger = logging.getLogger(__name__)


class UserErasureService:
    """Erase or anonymize all personal data for a single user."""

    def __init__(self, *, storage_service=None, audit_service=None) -> None:
        self._storage_service = storage_service
        self._audit_service = audit_service

    @property
    def _storage(self):
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

    def erase(self, user: User, *, requested_by: str = "admin") -> dict:
        firebase_uid = user.firebase_uid
        user_id = str(user.id)

        # 1) Delete blob objects: profile photo, verification docs, sent media.
        keys: list[str] = []
        if user.profile_photo_url:
            keys.append(user.profile_photo_url)
        for request in VerificationRequest.objects.filter(user=user):
            keys += [
                k
                for k in (request.college_id_image_url, request.gesture_selfie_image_url)
                if k
            ]
        keys += list(
            Message.objects.filter(sender=user)
            .exclude(media_url="")
            .values_list("media_url", flat=True)
        )
        blobs_deleted = 0
        for key in keys:
            try:
                self._storage.delete_object(key)
                blobs_deleted += 1
            except Exception:  # noqa: BLE001 — storage errors must not block erasure.
                logger.warning("erase_user: failed to delete blob for user %s", user_id)

        # 2) Hard-delete personal rows + anonymize the user row atomically.
        with transaction.atomic():
            summary = {
                "messages": Message.objects.filter(sender=user).delete()[0],
                "verification_requests": VerificationRequest.objects.filter(
                    user=user
                ).delete()[0],
                "device_tokens": DeviceToken.objects.filter(user=user).delete()[0],
                "notifications": Notification.objects.filter(user=user).delete()[0],
                "reveal_decisions": ParticipantDecision.objects.filter(
                    user=user
                ).delete()[0],
                "match_queue_entries": MatchQueue.objects.filter(user=user).delete()[0],
                "chat_participations": ChatParticipant.objects.filter(
                    user=user
                ).delete()[0],
                "ratings_given": Rating.objects.filter(rated_by=user).delete()[0],
            }

            # Payments (financial) + reports (safety) + ratings received keep a
            # PII-free reference; the row can't be hard-deleted (PROTECT), so scrub
            # every identifying field instead.
            user.firebase_uid = f"erased-{user_id}"
            user.college_email = f"erased-{user_id}@erased.invalid"
            user.full_name = ""
            user.profile_photo_url = ""
            user.gender = ""
            user.intent = ""
            user.gender_preferences = []
            user.verified_at = None
            user.account_status = AccountStatus.DELETED
            user.save()

        # 3) Delete the Firebase Auth identity (best effort).
        firebase_deleted = self._delete_firebase_user(firebase_uid)

        # 4) Audit the erasure (the record itself carries no PII).
        from apps.audit.enums import ActorType

        self._audit.log(
            actor_type=ActorType.ADMIN,
            actor_id=requested_by,
            action="user.erased",
            entity_type="user",
            entity_id=user_id,
            metadata={
                "blobs_deleted": blobs_deleted,
                "firebase_deleted": firebase_deleted,
                **summary,
            },
        )
        return {
            "user_id": user_id,
            "blobs_deleted": blobs_deleted,
            "firebase_deleted": firebase_deleted,
            **summary,
        }

    def _delete_firebase_user(self, firebase_uid: str) -> bool:
        if not firebase_uid:
            return False
        try:
            from firebase_admin import auth

            from apps.common.firebase import _get_app

            auth.delete_user(firebase_uid, app=_get_app())
            return True
        except Exception:  # noqa: BLE001 — user may not exist / Firebase unconfigured.
            logger.warning("erase_user: could not delete Firebase user %s", firebase_uid)
            return False
