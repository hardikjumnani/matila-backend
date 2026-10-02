"""API tests for admin college management (list + set launch date)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.colleges.models import College
from apps.users.models import User

_ADMIN_EMAIL = "admin@college.edu"


def _admin_client() -> APIClient:
    admin = User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex, college_email=_ADMIN_EMAIL
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


@override_settings(ADMIN_EMAILS=[_ADMIN_EMAIL])
class AdminCollegeAPITests(TestCase):
    def setUp(self) -> None:
        self.client = _admin_client()
        self.college = College.objects.create(
            code="BITS",
            name="BITS Pilani",
            allowed_email_domains=["bits.ac.in"],
            launch_date=timezone.now() + timedelta(days=5),
        )

    def test_list_includes_launch_state_and_counts(self) -> None:
        User.objects.create(
            firebase_uid="fb_" + uuid.uuid4().hex,
            college_email=f"{uuid.uuid4().hex}@bits.ac.in",
            college=self.college,
        )
        response = self.client.get("/api/v1/admin/colleges")
        self.assertEqual(response.status_code, 200)
        rows = {c["code"]: c for c in response.json()["data"]}
        self.assertIn("BITS", rows)
        self.assertFalse(rows["BITS"]["is_launched"])
        self.assertEqual(rows["BITS"]["user_count"], 1)

    def test_patch_sets_launch_date_and_audits(self) -> None:
        new_launch = (timezone.now() + timedelta(days=1)).replace(microsecond=0)
        response = self.client.patch(
            f"/api/v1/admin/colleges/{self.college.id}",
            {"launch_date": new_launch.isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.college.refresh_from_db()
        self.assertEqual(self.college.launch_date, new_launch)
        self.assertTrue(
            AuditLog.objects.filter(
                action="college.updated", entity_id=str(self.college.id)
            ).exists()
        )

    def test_patch_can_unset_launch_date(self) -> None:
        response = self.client.patch(
            f"/api/v1/admin/colleges/{self.college.id}",
            {"launch_date": None},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.college.refresh_from_db()
        self.assertIsNone(self.college.launch_date)

    def test_patch_unknown_college_404(self) -> None:
        response = self.client.patch(
            f"/api/v1/admin/colleges/{uuid.uuid4()}",
            {"launch_date": None},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_empty_patch_rejected(self) -> None:
        response = self.client.patch(
            f"/api/v1/admin/colleges/{self.college.id}", {}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_non_admin_forbidden(self) -> None:
        client = APIClient()
        client.force_authenticate(
            user=User.objects.create(
                firebase_uid="fb_" + uuid.uuid4().hex,
                college_email=f"{uuid.uuid4().hex}@college.edu",
            )
        )
        response = client.get("/api/v1/admin/colleges")
        self.assertEqual(response.status_code, 403)
