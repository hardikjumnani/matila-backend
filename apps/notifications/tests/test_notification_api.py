"""API tests for the notifications endpoints."""

from __future__ import annotations

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from apps.notifications.services.notification_service import NotificationService
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class NotificationApiTests(TestCase):
    def setUp(self) -> None:
        self.user = _user()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.service = NotificationService()
        for i in range(3):
            self.service.create_notification(user=self.user, type="test", title=f"N{i}")

    def test_list(self) -> None:
        response = self.client.get("/api/v1/notifications")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]["items"]), 3)

    def test_unread_count(self) -> None:
        response = self.client.get("/api/v1/notifications/unread-count")
        self.assertEqual(response.json()["data"]["unread_count"], 3)

    def test_mark_one_read(self) -> None:
        notif = self.service.create_notification(user=self.user, type="t", title="X")
        response = self.client.post(f"/api/v1/notifications/{notif.id}/read")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["is_read"])

    def test_mark_all_read(self) -> None:
        response = self.client.post("/api/v1/notifications/read-all")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["marked_read"], 3)
        count = self.client.get("/api/v1/notifications/unread-count")
        self.assertEqual(count.json()["data"]["unread_count"], 0)

    def test_only_own_notifications(self) -> None:
        other_notif = self.service.create_notification(
            user=_user(), type="t", title="other"
        )
        response = self.client.post(f"/api/v1/notifications/{other_notif.id}/read")
        self.assertEqual(response.status_code, 404)
