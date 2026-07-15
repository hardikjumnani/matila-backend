"""API tests for the admin verification-review and report-moderation endpoints."""

from __future__ import annotations

import uuid

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.chats.services.chat_service import ChatService
from apps.reports.enums import ReportCategory, ReportStatus, ResolutionAction
from apps.reports.models import Report
from apps.users.enums import AccountStatus, VerificationStatus
from apps.users.models import User
from apps.verification.models import VerificationRequest

_ADMIN_EMAIL = "admin@college.edu"


def _user(email=None) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=email or f"{uuid.uuid4().hex}@college.edu",
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminAccessTests(TestCase):
    def test_non_admin_forbidden(self) -> None:
        response = _client(_user()).get("/api/v1/admin/verifications")
        self.assertEqual(response.status_code, 403)

    def test_admin_allowed(self) -> None:
        admin = _user(_ADMIN_EMAIL)
        response = _client(admin).get("/api/v1/admin/verifications")
        self.assertEqual(response.status_code, 200)


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminVerificationTests(TestCase):
    def setUp(self) -> None:
        self.admin = _user(_ADMIN_EMAIL)
        self.client = _client(self.admin)
        self.target = _user()
        self.request = VerificationRequest.objects.create(
            user=self.target,
            attempt_number=1,
            status=VerificationStatus.PENDING,
            gesture_type="WAVE",
            college_id_image_url="verification/college-id/x.jpg",
            gesture_selfie_image_url="verification/gesture-selfie/y.jpg",
            submitted_at=timezone.now(),
        )

    def test_list_shows_pending(self) -> None:
        response = self.client.get("/api/v1/admin/verifications")
        items = response.json()["data"]["items"]
        self.assertEqual(len(items), 1)
        # Admin serializer exposes document URLs.
        self.assertTrue(items[0]["college_id_image_url"])

    def test_approve_verifies_user_and_records_admin(self) -> None:
        response = self.client.post(
            f"/api/v1/admin/verifications/{self.request.id}/approve",
            {"notes": "looks good"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.request.refresh_from_db()
        self.assertEqual(self.target.verification_status, VerificationStatus.APPROVED)
        self.assertEqual(self.request.reviewed_by_id, self.admin.id)

    def test_reject(self) -> None:
        response = self.client.post(
            f"/api/v1/admin/verifications/{self.request.id}/reject",
            {"notes": "blurry"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.verification_status, VerificationStatus.REJECTED)


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminReportTests(TestCase):
    def setUp(self) -> None:
        self.admin = _user(_ADMIN_EMAIL)
        self.client = _client(self.admin)
        self.a = _user()
        self.b = _user()
        self.chat = ChatService().create_chat(self.a, self.b).data
        self.report = Report.objects.create(
            chat=self.chat,
            reported_by=self.a,
            reported_user=self.b,
            category=ReportCategory.HARASSMENT,
            status=ReportStatus.OPEN,
        )

    def test_list_open_reports(self) -> None:
        response = self.client.get("/api/v1/admin/reports")
        self.assertEqual(len(response.json()["data"]["items"]), 1)

    def test_detail_includes_evidence(self) -> None:
        response = self.client.get(f"/api/v1/admin/reports/{self.report.id}")
        body = response.json()["data"]
        self.assertIn("report", body)
        self.assertIn("messages", body)

    def test_resolve_with_ban(self) -> None:
        response = self.client.post(
            f"/api/v1/admin/reports/{self.report.id}/resolve",
            {"resolution_action": ResolutionAction.PERMANENT_BAN},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.b.refresh_from_db()
        self.assertEqual(self.b.account_status, AccountStatus.BANNED)

    def test_dismiss_false_report(self) -> None:
        response = self.client.post(
            f"/api/v1/admin/reports/{self.report.id}/dismiss",
            {"is_false_report": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["is_false_report"])
