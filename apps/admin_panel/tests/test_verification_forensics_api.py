"""Admin serializer exposure of verification image forensics."""

from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone

from apps.admin_panel.api.serializers import (
    AdminVerificationDetailSerializer,
    AdminVerificationRequestSerializer,
)
from apps.users.enums import VerificationStatus
from apps.users.models import User
from apps.verification.models import VerificationRequest

_OK_REPORT = {"overall": "ok", "signals": [{"key": "decodable", "verdict": "ok"}]}
_BAD_REPORT = {
    "overall": "attention",
    "signals": [{"key": "editor", "verdict": "attention", "note": "Photoshop"}],
}


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        onboarding_completed_at=timezone.now(),
    )


def _request(user, **overrides) -> VerificationRequest:
    data = {
        "user": user,
        "attempt_number": 1,
        "status": VerificationStatus.APPROVED,  # any status, not just pending
        "submitted_at": timezone.now(),
    }
    data.update(overrides)
    return VerificationRequest.objects.create(**data)


class VerificationForensicsSerializerTests(TestCase):
    def test_list_serializer_exposes_overall_and_report(self) -> None:
        req = _request(_user(), gesture_selfie_forensics=_BAD_REPORT,
                       college_id_forensics=_OK_REPORT)
        data = AdminVerificationRequestSerializer(req).data
        self.assertEqual(data["forensics_overall"], "attention")
        self.assertEqual(data["forensics"]["selfie"]["overall"], "attention")
        self.assertTrue(data["forensics"]["selfie"]["signals"])
        self.assertEqual(data["forensics"]["college_id"]["overall"], "ok")
        # Duplicates are a detail-only (live) signal; list keeps it empty.
        self.assertEqual(data["forensics"]["duplicates"], [])

    def test_overall_ok_when_both_clean(self) -> None:
        req = _request(_user(), gesture_selfie_forensics=_OK_REPORT,
                       college_id_forensics=_OK_REPORT)
        data = AdminVerificationRequestSerializer(req).data
        self.assertEqual(data["forensics_overall"], "ok")

    def test_available_on_any_status_not_just_pending(self) -> None:
        for status in (VerificationStatus.APPROVED, VerificationStatus.REJECTED):
            req = _request(_user(), status=status, gesture_selfie_forensics=_OK_REPORT)
            data = AdminVerificationRequestSerializer(req).data
            self.assertIn("forensics", data)
            self.assertEqual(data["status"], status)

    def test_detail_serializer_includes_live_duplicates(self) -> None:
        user_a = _user()
        user_b = _user()
        _request(user_a, selfie_sha256="deadbeef", selfie_phash="1111111111111111")
        req_b = _request(user_b, selfie_sha256="deadbeef",
                         selfie_phash="1111111111111111",
                         gesture_selfie_forensics=_OK_REPORT)
        data = AdminVerificationDetailSerializer(req_b).data
        dups = data["forensics"]["duplicates"]
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["user_id"], str(user_a.id))
        # A duplicate forces the overall to attention even if the image looked ok.
        self.assertEqual(data["forensics"]["overall"], "attention")
