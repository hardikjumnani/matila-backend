"""Tests for the send_push_notification task (FCM mocked)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.test import TestCase

from apps.common.firebase import FirebaseNotConfigured, PushResult
from apps.notifications.enums import DevicePlatform, PushStatus
from apps.notifications.models import DeviceToken, Notification
from apps.notifications.tasks.push import send_push_notification
from apps.users.models import User

_SEND = "apps.common.firebase.send_push"


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class SendPushNotificationTests(TestCase):
    def setUp(self) -> None:
        self.user = _user()
        self.notification = Notification.objects.create(
            user=self.user, type="test", title="Hi", body="There"
        )

    def _add_token(self, token="tok-1") -> DeviceToken:
        return DeviceToken.objects.create(
            user=self.user, token=token, device_id="dev-1", platform=DevicePlatform.IOS
        )

    def test_no_tokens_skips(self) -> None:
        send_push_notification(str(self.notification.id))
        self.notification.refresh_from_db()
        self.assertEqual(self.notification.push_status, PushStatus.SKIPPED)

    def test_successful_delivery(self) -> None:
        self._add_token()
        with mock.patch(
            _SEND,
            return_value=PushResult(
                success_count=1, failure_count=0, invalid_tokens=[]
            ),
        ):
            send_push_notification(str(self.notification.id))
        self.notification.refresh_from_db()
        self.assertEqual(self.notification.push_status, PushStatus.SENT)

    def test_invalid_tokens_deactivated(self) -> None:
        self._add_token("dead")
        with mock.patch(
            _SEND,
            return_value=PushResult(
                success_count=0, failure_count=1, invalid_tokens=["dead"]
            ),
        ):
            send_push_notification(str(self.notification.id))
        self.notification.refresh_from_db()
        self.assertEqual(self.notification.push_status, PushStatus.FAILED)
        self.assertFalse(DeviceToken.objects.get(token="dead").is_active)

    def test_firebase_not_configured_skips(self) -> None:
        self._add_token()
        with mock.patch(_SEND, side_effect=FirebaseNotConfigured()):
            send_push_notification(str(self.notification.id))
        self.notification.refresh_from_db()
        self.assertEqual(self.notification.push_status, PushStatus.SKIPPED)

    def test_already_sent_is_idempotent(self) -> None:
        self._add_token()
        self.notification.push_status = PushStatus.SENT
        self.notification.save(update_fields=["push_status"])
        with mock.patch(_SEND) as send:
            send_push_notification(str(self.notification.id))
            send.assert_not_called()
