"""Tests for DeviceTokenService and the device registration endpoints."""

from __future__ import annotations

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from apps.notifications.enums import DevicePlatform
from apps.notifications.models import DeviceToken
from apps.notifications.services.device_token_service import DeviceTokenService
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class DeviceTokenServiceTests(TestCase):
    def setUp(self) -> None:
        self.service = DeviceTokenService()
        self.user = _user()

    def test_register_creates(self) -> None:
        result = self.service.register(
            user=self.user,
            token="tok-1",
            device_id="dev-1",
            platform=DevicePlatform.ANDROID,
        )
        self.assertTrue(result.success)
        self.assertEqual(DeviceToken.objects.filter(user=self.user).count(), 1)

    def test_rotation_updates_same_device_row(self) -> None:
        self.service.register(
            user=self.user,
            token="tok-1",
            device_id="dev-1",
            platform=DevicePlatform.IOS,
        )
        self.service.register(
            user=self.user,
            token="tok-2",
            device_id="dev-1",
            platform=DevicePlatform.IOS,
        )
        rows = DeviceToken.objects.filter(user=self.user, device_id="dev-1")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().token, "tok-2")

    def test_token_detached_from_other_device(self) -> None:
        self.service.register(
            user=self.user,
            token="shared",
            device_id="dev-1",
            platform=DevicePlatform.IOS,
        )
        # Same token now registered by a different device: the old row is removed.
        self.service.register(
            user=self.user,
            token="shared",
            device_id="dev-2",
            platform=DevicePlatform.IOS,
        )
        self.assertFalse(DeviceToken.objects.filter(device_id="dev-1").exists())
        self.assertEqual(DeviceToken.objects.filter(token="shared").count(), 1)

    def test_deactivate_device(self) -> None:
        self.service.register(
            user=self.user, token="t", device_id="dev-1", platform=DevicePlatform.IOS
        )
        result = self.service.deactivate_device(user=self.user, device_id="dev-1")
        self.assertTrue(result.success)
        self.assertFalse(self.service.active_tokens_for(self.user).exists())

    def test_deactivate_tokens_by_value(self) -> None:
        self.service.register(
            user=self.user, token="dead", device_id="dev-1", platform=DevicePlatform.IOS
        )
        self.assertEqual(self.service.deactivate_tokens(["dead"]), 1)


class DeviceApiTests(TestCase):
    def setUp(self) -> None:
        self.user = _user()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_register_endpoint(self) -> None:
        response = self.client.post(
            "/api/v1/users/me/devices",
            {"token": "tok", "device_id": "dev-1", "platform": "ANDROID"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["device_id"], "dev-1")

    def test_logout_endpoint(self) -> None:
        self.client.post(
            "/api/v1/users/me/devices",
            {"token": "tok", "device_id": "dev-1", "platform": "ANDROID"},
            format="json",
        )
        response = self.client.delete("/api/v1/users/me/devices/dev-1")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["deactivated"])

    def test_logout_unknown_device(self) -> None:
        response = self.client.delete("/api/v1/users/me/devices/nope")
        self.assertEqual(response.status_code, 404)
