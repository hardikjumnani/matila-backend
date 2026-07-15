"""Tests for NotificationService (in-app lifecycle)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.notifications.enums import PushStatus
from apps.notifications.models import Notification
from apps.notifications.services.notification_service import NotificationService
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class NotificationServiceTests(TestCase):
    def setUp(self) -> None:
        self.service = NotificationService()
        self.user = _user()

    def test_create_notification_defaults_to_pending_push(self) -> None:
        n = self.service.create_notification(
            user=self.user, type="verification.approved", title="Approved"
        )
        self.assertEqual(n.push_status, PushStatus.PENDING)
        self.assertFalse(n.is_read)

    def test_unread_count_excludes_read_and_expired(self) -> None:
        self.service.create_notification(user=self.user, type="a", title="A")
        read = self.service.create_notification(user=self.user, type="b", title="B")
        self.service.mark_read(user=self.user, notification_id=str(read.id))
        Notification.objects.create(
            user=self.user,
            type="c",
            title="C",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertEqual(self.service.get_unread_count(self.user), 1)

    def test_mark_read_is_idempotent(self) -> None:
        n = self.service.create_notification(user=self.user, type="a", title="A")
        r1 = self.service.mark_read(user=self.user, notification_id=str(n.id))
        r2 = self.service.mark_read(user=self.user, notification_id=str(n.id))
        self.assertTrue(r1.success and r2.success)
        self.assertTrue(r2.data.is_read)

    def test_mark_read_unknown_returns_not_found(self) -> None:
        result = self.service.mark_read(
            user=self.user, notification_id=str(uuid.uuid4())
        )
        self.assertEqual(result.error_code, "RESOURCE_NOT_FOUND")

    def test_mark_read_other_users_notification_is_not_found(self) -> None:
        other = self.service.create_notification(user=_user(), type="a", title="A")
        result = self.service.mark_read(user=self.user, notification_id=str(other.id))
        self.assertEqual(result.error_code, "RESOURCE_NOT_FOUND")

    def test_mark_all_read_returns_count(self) -> None:
        for i in range(3):
            self.service.create_notification(user=self.user, type="t", title=str(i))
        count = self.service.mark_all_read(user=self.user)
        self.assertEqual(count, 3)
        self.assertEqual(self.service.get_unread_count(self.user), 0)
