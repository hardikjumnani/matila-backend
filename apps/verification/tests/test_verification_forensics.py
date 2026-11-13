"""Integration: forensics attach on upload + cross-user duplicate detection."""

from __future__ import annotations

import io
import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from PIL import Image, ImageDraw

from apps.common.services.storage_service import StorageService
from apps.configuration.services.configuration_service import ConfigurationService
from apps.users.models import User
from apps.verification.models import VerificationRequest
from apps.verification.services.verification_service import VerificationService


def _jpeg(color=(120, 90, 160)) -> bytes:
    # Non-flat, colour-dependent content so the perceptual hash is meaningful and
    # differs between distinct colours (a flat fill hashes to all-zeros).
    img = Image.new("RGB", (400, 400), color)
    draw = ImageDraw.Draw(img)
    inv = tuple(255 - c for c in color)
    draw.rectangle([100, 100, 200, 200], fill=inv)
    draw.ellipse([200, 150, 320, 280], fill=(color[2], color[0], color[1]))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        onboarding_completed_at=timezone.now(),
    )


class VerificationForensicsIntegrationTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.storage = mock.MagicMock()
        self.storage.build_key.side_effect = StorageService.build_key
        self.storage.upload_fileobj.side_effect = (
            lambda fileobj, key, content_type=None: key
        )
        self.service = VerificationService(
            configuration_service=ConfigurationService(),
            storage_service=self.storage,
            notification_service=mock.MagicMock(),
            audit_service=mock.MagicMock(),
        )

    def test_upload_selfie_attaches_forensics_and_hashes(self) -> None:
        user = _user()
        self.service.upload_gesture_selfie(
            user, fileobj=io.BytesIO(_jpeg()), filename="s.jpg",
            content_type="image/jpeg",
        )
        draft = VerificationRequest.objects.get(user=user)
        self.assertTrue(draft.gesture_selfie_forensics.get("signals"))
        self.assertIn(draft.gesture_selfie_forensics["overall"], ("ok", "attention"))
        self.assertTrue(draft.selfie_sha256)
        self.assertTrue(draft.selfie_phash)

    def test_forensics_is_non_blocking_on_bad_bytes(self) -> None:
        user = _user()
        result = self.service.upload_gesture_selfie(
            user, fileobj=io.BytesIO(b"not an image"), filename="s.jpg",
            content_type="image/jpeg",
        )
        self.assertTrue(result.success)  # upload still succeeds
        draft = VerificationRequest.objects.get(user=user)
        self.assertTrue(draft.gesture_selfie_image_url)  # stored anyway
        self.assertEqual(draft.gesture_selfie_forensics["overall"], "attention")

    def test_college_id_forensics_stored_separately(self) -> None:
        user = _user()
        self.service.upload_college_id(
            user, fileobj=io.BytesIO(_jpeg()), filename="id.jpg",
            content_type="image/jpeg",
        )
        draft = VerificationRequest.objects.get(user=user)
        self.assertTrue(draft.college_id_forensics.get("signals"))
        # College-id upload populates the college hashes, not the selfie ones.
        self.assertTrue(draft.college_id_sha256)
        self.assertEqual(draft.selfie_sha256, "")

    def test_duplicate_selfie_detected_across_users(self) -> None:
        shared = _jpeg(color=(10, 200, 50))
        user_a = _user()
        user_b = _user()
        self.service.upload_gesture_selfie(
            user_a, fileobj=io.BytesIO(shared), filename="s.jpg",
            content_type="image/jpeg",
        )
        self.service.upload_gesture_selfie(
            user_b, fileobj=io.BytesIO(shared), filename="s.jpg",
            content_type="image/jpeg",
        )
        req_b = VerificationRequest.objects.get(user=user_b)
        dups = self.service.find_selfie_duplicates(req_b)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["user_id"], str(user_a.id))
        self.assertEqual(dups[0]["kind"], "exact")

    def test_no_duplicate_for_distinct_selfies(self) -> None:
        user_a = _user()
        user_b = _user()
        self.service.upload_gesture_selfie(
            user_a, fileobj=io.BytesIO(_jpeg(color=(1, 2, 3))), filename="s.jpg",
            content_type="image/jpeg",
        )
        self.service.upload_gesture_selfie(
            user_b, fileobj=io.BytesIO(_jpeg(color=(250, 240, 230))), filename="s.jpg",
            content_type="image/jpeg",
        )
        req_b = VerificationRequest.objects.get(user=user_b)
        self.assertEqual(self.service.find_selfie_duplicates(req_b), [])
