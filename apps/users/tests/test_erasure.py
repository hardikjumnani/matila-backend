"""Tests for UserErasureService (storage + Firebase mocked)."""

from __future__ import annotations

from unittest import mock

from django.test import TestCase

from apps.chats.models import Chat, ChatParticipant
from apps.matchmaking.models import MatchQueue
from apps.messaging.models import Message
from apps.notifications.models import DeviceToken, Notification
from apps.payments.models import Payment
from apps.ratings.models import Rating
from apps.reveal.models import RevealIntent
from apps.users.enums import AccountStatus
from apps.users.models import User
from apps.users.services.erasure_service import UserErasureService
from apps.verification.models import VerificationRequest

_DELETE_OBJECT = "apps.common.services.storage_service.StorageService.delete_object"
_DELETE_FB = "apps.users.services.erasure_service.UserErasureService._delete_firebase_user"


class UserErasureServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create(
            firebase_uid="fb_user",
            college_email="alice@college.edu",
            full_name="Alice",
            gender="FEMALE",
            intent="RELATIONSHIP",
            gender_preferences=["MALE"],
            profile_photo_url="profile-photos/1.jpg",
        )
        self.other = User.objects.create(
            firebase_uid="fb_other", college_email="bob@college.edu"
        )
        self.chat = Chat.objects.create()
        ChatParticipant.objects.create(chat=self.chat, user=self.user)
        ChatParticipant.objects.create(chat=self.chat, user=self.other)
        Message.objects.create(
            chat=self.chat, sender=self.user, message_type="IMAGE",
            media_url="chat/img.jpg",
        )
        VerificationRequest.objects.create(
            user=self.user, attempt_number=1,
            college_id_image_url="verif/id.jpg",
            gesture_selfie_image_url="verif/selfie.jpg",
        )
        DeviceToken.objects.create(
            user=self.user, token="tok", device_id="d1", platform="ANDROID"
        )
        Notification.objects.create(user=self.user, type="x", title="hi")
        RevealIntent.objects.create(chat=self.chat, user=self.user)
        MatchQueue.objects.create(user=self.user, intent="RELATIONSHIP")
        Rating.objects.create(
            chat=self.chat, rated_by=self.user, rated_user=self.other,
            questionnaire_version="v1", responses={},
        )
        self.payment = Payment.objects.create(
            user=self.user, chat=self.chat, purpose="REVEAL", amount_in_paise=5900,
            status="SUCCESS", initiated_from="CHAT_SCREEN", provider_order_id="order_1",
        )

    def test_erase_removes_personal_data_and_anonymizes(self) -> None:
        with mock.patch(_DELETE_OBJECT) as delete_object, mock.patch(
            _DELETE_FB, return_value=True
        ):
            summary = UserErasureService().erase(self.user, requested_by="ops")

        # Personal rows hard-deleted.
        self.assertEqual(Message.objects.filter(sender=self.user).count(), 0)
        self.assertEqual(VerificationRequest.objects.filter(user=self.user).count(), 0)
        self.assertEqual(DeviceToken.objects.filter(user=self.user).count(), 0)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 0)
        self.assertEqual(RevealIntent.objects.filter(user=self.user).count(), 0)
        self.assertEqual(MatchQueue.objects.filter(user=self.user).count(), 0)
        self.assertEqual(ChatParticipant.objects.filter(user=self.user).count(), 0)
        self.assertEqual(Rating.objects.filter(rated_by=self.user).count(), 0)

        # Blob deletions: profile + 2 verification docs + 1 sent media = 4.
        self.assertEqual(delete_object.call_count, 4)

        # Payment retained (financial), now pointing at the scrubbed row.
        self.assertEqual(Payment.objects.filter(id=self.payment.id).count(), 1)

        # User row anonymized, not deleted.
        self.user.refresh_from_db()
        self.assertEqual(self.user.account_status, AccountStatus.DELETED)
        self.assertEqual(self.user.full_name, "")
        self.assertEqual(self.user.gender, "")
        self.assertEqual(self.user.gender_preferences, [])
        self.assertTrue(self.user.college_email.startswith("erased-"))
        self.assertTrue(self.user.firebase_uid.startswith("erased-"))
        self.assertTrue(summary["firebase_deleted"])

    def test_erase_is_idempotent(self) -> None:
        with mock.patch(_DELETE_OBJECT), mock.patch(_DELETE_FB, return_value=True):
            UserErasureService().erase(self.user)
            # Second run on the already-erased user must not error.
            summary = UserErasureService().erase(self.user)
        self.assertEqual(summary["messages"], 0)
