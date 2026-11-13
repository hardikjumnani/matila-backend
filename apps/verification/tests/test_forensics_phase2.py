"""Phase 2: near-duplicate (Hamming) matching, college-ID reuse, backfill."""

from __future__ import annotations

import io
import uuid
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from apps.users.models import User
from apps.verification.models import VerificationRequest
from apps.verification.services.verification_service import _hamming
from apps.verification.services.verification_service import VerificationService


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        onboarding_completed_at=timezone.now(),
    )


def _req(user, **overrides) -> VerificationRequest:
    data = {"user": user, "attempt_number": 1, "submitted_at": timezone.now()}
    data.update(overrides)
    return VerificationRequest.objects.create(**data)


def _jpeg() -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (400, 400), (30, 60, 90))
    for x in range(0, 400, 40):  # stripes -> non-degenerate phash
        for y in range(400):
            img.putpixel((x, y), (200, 100, 50))
    img.save(buf, format="JPEG")
    return buf.getvalue()


class HammingTests(TestCase):
    def test_hamming_basic(self) -> None:
        self.assertEqual(_hamming("0000000000000000", "0000000000000000"), 0)
        self.assertEqual(_hamming("1234abcd1234abcd", "1234abcd1234abce"), 2)
        self.assertEqual(_hamming("bad", "zzz"), 64)  # unparseable -> max distance


class NearDuplicateTests(TestCase):
    def setUp(self) -> None:
        self.svc = VerificationService(
            configuration_service=mock.MagicMock(),
            storage_service=mock.MagicMock(),
            notification_service=mock.MagicMock(),
            audit_service=mock.MagicMock(),
        )

    def test_near_duplicate_phash_is_matched(self) -> None:
        a = _user()
        b = _user()
        _req(a, selfie_phash="1234abcd1234abcd", selfie_sha256="aaa")
        rb = _req(b, selfie_phash="1234abcd1234abce", selfie_sha256="bbb")  # 2 bits off
        dups = self.svc.find_selfie_duplicates(rb)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["user_id"], str(a.id))
        self.assertEqual(dups[0]["kind"], "near")

    def test_far_phash_is_not_matched(self) -> None:
        a = _user()
        b = _user()
        _req(a, selfie_phash="ffffffff00000000", selfie_sha256="aaa")
        rb = _req(b, selfie_phash="0000000011111111", selfie_sha256="bbb")
        self.assertEqual(self.svc.find_selfie_duplicates(rb), [])

    def test_college_id_reuse_detected(self) -> None:
        a = _user()
        b = _user()
        _req(a, college_id_sha256="sharedsha")
        rb = _req(b, college_id_sha256="sharedsha")
        dups = self.svc.find_college_id_duplicates(rb)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["image"], "college_id")
        self.assertEqual(dups[0]["kind"], "exact")

    def test_find_duplicates_merges_both_images(self) -> None:
        a = _user()
        b = _user()
        _req(a, selfie_sha256="s1", college_id_sha256="c1")
        rb = _req(b, selfie_sha256="s1", college_id_sha256="c1")
        images = {d["image"] for d in self.svc.find_duplicates(rb)}
        self.assertEqual(images, {"selfie", "college_id"})

    def test_degenerate_phash_not_matched(self) -> None:
        a = _user()
        b = _user()
        _req(a, selfie_phash="0000000000000000", selfie_sha256="aaa")
        rb = _req(b, selfie_phash="0000000000000000", selfie_sha256="bbb")
        self.assertEqual(self.svc.find_selfie_duplicates(rb), [])


class BackfillTests(TestCase):
    def test_backfill_populates_missing_forensics(self) -> None:
        req = _req(_user(), gesture_selfie_image_url="verification/gesture-selfie/x.jpg")
        with mock.patch(
            "apps.common.services.storage_service.StorageService.download_bytes",
            return_value=(_jpeg(), "image/jpeg"),
        ):
            call_command("backfill_verification_forensics", stdout=StringIO(), stderr=StringIO())
        req.refresh_from_db()
        self.assertTrue(req.gesture_selfie_forensics.get("signals"))
        self.assertTrue(req.selfie_sha256)
        self.assertTrue(req.selfie_phash)

    def test_backfill_dry_run_writes_nothing(self) -> None:
        req = _req(_user(), gesture_selfie_image_url="verification/gesture-selfie/x.jpg")
        with mock.patch(
            "apps.common.services.storage_service.StorageService.download_bytes",
            return_value=(_jpeg(), "image/jpeg"),
        ) as dl:
            call_command("backfill_verification_forensics", "--dry-run",
                         stdout=StringIO(), stderr=StringIO())
        req.refresh_from_db()
        self.assertEqual(req.gesture_selfie_forensics, {})
        dl.assert_not_called()

    def test_backfill_skips_already_populated_unless_all(self) -> None:
        req = _req(_user(), gesture_selfie_image_url="verification/gesture-selfie/x.jpg",
                   gesture_selfie_forensics={"overall": "ok", "signals": [1]})
        with mock.patch(
            "apps.common.services.storage_service.StorageService.download_bytes",
            return_value=(_jpeg(), "image/jpeg"),
        ) as dl:
            call_command("backfill_verification_forensics", stdout=StringIO(), stderr=StringIO())
        dl.assert_not_called()  # already has a report, not --all
