"""API tests for admin user/config/audit/dashboard management."""

from __future__ import annotations

import uuid

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.configuration.constants import FeatureFlagKey
from apps.configuration.models import FeatureFlag
from apps.configuration.services.configuration_service import ConfigurationService
from apps.users.enums import AccountStatus
from apps.users.models import User

_ADMIN_EMAIL = "admin@college.edu"


def _user(email=None) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=email or f"{uuid.uuid4().hex}@college.edu",
    )


def _admin_client() -> tuple[APIClient, User]:
    admin = _user(_ADMIN_EMAIL)
    client = APIClient()
    client.force_authenticate(user=admin)
    return client, admin


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminUserManagementTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.client, self.admin = _admin_client()
        self.target = _user()

    def test_list_and_search(self) -> None:
        response = self.client.get("/api/v1/admin/users")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["data"]["items"]), 2)

    def test_detail_includes_chat_summary(self) -> None:
        response = self.client.get(f"/api/v1/admin/users/{self.target.id}")
        body = response.json()["data"]
        self.assertEqual(body["user"]["id"], str(self.target.id))
        self.assertIn("chat_summary", body)

    def test_ban_updates_status_and_audits(self) -> None:
        response = self.client.post(f"/api/v1/admin/users/{self.target.id}/ban")
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.account_status, AccountStatus.BANNED)
        self.assertTrue(
            AuditLog.objects.filter(
                action="user.status.banned", entity_id=str(self.target.id)
            ).exists()
        )

    def test_suspend_then_activate(self) -> None:
        self.client.post(f"/api/v1/admin/users/{self.target.id}/suspend")
        self.target.refresh_from_db()
        self.assertEqual(self.target.account_status, AccountStatus.SUSPENDED)
        self.client.post(f"/api/v1/admin/users/{self.target.id}/activate")
        self.target.refresh_from_db()
        self.assertEqual(self.target.account_status, AccountStatus.ACTIVE)


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminConfigManagementTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.client, self.admin = _admin_client()

    def test_update_feature_flag_invalidates_cache(self) -> None:
        # Prime the cache with the default (enabled).
        self.assertTrue(
            ConfigurationService().is_feature_enabled(FeatureFlagKey.PAYMENTS_ENABLED)
        )
        response = self.client.put(
            f"/api/v1/admin/feature-flags/{FeatureFlagKey.PAYMENTS_ENABLED}",
            {"value": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            FeatureFlag.objects.filter(key=FeatureFlagKey.PAYMENTS_ENABLED).exists()
        )
        # Cache was invalidated: the new value is visible immediately.
        self.assertFalse(
            ConfigurationService().is_feature_enabled(FeatureFlagKey.PAYMENTS_ENABLED)
        )
        self.assertTrue(AuditLog.objects.filter(action="feature_flag.updated").exists())

    def test_update_app_config(self) -> None:
        response = self.client.put(
            "/api/v1/admin/app-config/reveal_price_paise",
            {"value": 7000},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ConfigurationService().get_reveal_price_paise(), 7000)

    def test_flag_list(self) -> None:
        response = self.client.get("/api/v1/admin/feature-flags")
        self.assertEqual(response.status_code, 200)
        self.assertIn(FeatureFlagKey.PAYMENTS_ENABLED, response.json()["data"])


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminAuditAndDashboardTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.client, self.admin = _admin_client()

    def test_audit_log_list_filtered(self) -> None:
        target = _user()
        self.client.post(f"/api/v1/admin/users/{target.id}/suspend")
        response = self.client.get("/api/v1/admin/audit-logs?entity_type=user")
        items = response.json()["data"]["items"]
        self.assertTrue(any(i["action"] == "user.status.suspended" for i in items))

    def test_dashboard_stats(self) -> None:
        response = self.client.get("/api/v1/admin/dashboard/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        for key in ("users", "verifications", "chats", "reports", "revenue"):
            self.assertIn(key, data)

    def test_non_admin_denied(self) -> None:
        client = APIClient()
        client.force_authenticate(user=_user())
        self.assertEqual(client.get("/api/v1/admin/dashboard/stats").status_code, 403)
