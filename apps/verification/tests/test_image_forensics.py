"""Unit tests for verification image forensics (report-only)."""

from __future__ import annotations

import io
from datetime import datetime

from django.test import TestCase
from PIL import Image

from apps.verification.services.image_forensics import analyze_image


def _jpeg(exif=None, size=(400, 400), color=(100, 120, 140)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    if exif is not None:
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def _verdict(report: dict, key: str):
    for sig in report["signals"]:
        if sig["key"] == key:
            return sig["verdict"]
    return None


class ImageForensicsTests(TestCase):
    def test_clean_jpeg_no_metadata_is_ok(self) -> None:
        report = analyze_image(_jpeg(), declared_content_type="image/jpeg", filename="s.jpg")
        self.assertEqual(_verdict(report, "decodable"), "ok")
        # Absence of metadata is NOT flagged red (clean re-encode is normal).
        self.assertEqual(_verdict(report, "metadata_integrity"), "info")
        self.assertEqual(report["overall"], "ok")
        self.assertTrue(report["sha256"])
        self.assertTrue(report["phash"])

    def test_editor_software_is_flagged(self) -> None:
        exif = Image.Exif()
        exif[305] = "Adobe Photoshop 25.0"
        report = analyze_image(_jpeg(exif), declared_content_type="image/jpeg", filename="s.jpg")
        self.assertEqual(_verdict(report, "editor"), "attention")
        self.assertEqual(report["overall"], "attention")

    def test_selective_scrub_is_flagged(self) -> None:
        # EXIF structure remains (ImageDescription/Orientation) but the identifying
        # fields (Make/Model/DateTimeOriginal) are gone: selective-removal signature.
        exif = Image.Exif()
        exif[270] = "copy"   # ImageDescription (non-identifying, reliably written)
        exif[274] = 6        # Orientation
        report = analyze_image(_jpeg(exif), declared_content_type="image/jpeg", filename="s.jpg")
        self.assertEqual(_verdict(report, "metadata_integrity"), "attention")
        self.assertEqual(report["overall"], "attention")

    def test_consistent_camera_metadata_is_ok(self) -> None:
        exif = Image.Exif()
        exif[271] = "Apple"
        exif[272] = "iPhone 14"
        exif[306] = "2026:11:13 10:00:00"
        report = analyze_image(
            _jpeg(exif), declared_content_type="image/jpeg", filename="s.jpg",
            reference_time=datetime(2026, 11, 13, 9, 0, 0),
        )
        self.assertEqual(_verdict(report, "metadata_integrity"), "ok")
        self.assertEqual(_verdict(report, "capture_time"), "ok")

    def test_capture_before_attempt_is_flagged(self) -> None:
        exif = Image.Exif()
        exif[306] = "2020:01:01 10:00:00"
        report = analyze_image(
            _jpeg(exif), declared_content_type="image/jpeg", filename="s.jpg",
            reference_time=datetime(2026, 11, 13, 9, 0, 0),
        )
        self.assertEqual(_verdict(report, "capture_time"), "attention")
        self.assertEqual(report["overall"], "attention")

    def test_format_mismatch_is_flagged(self) -> None:
        img = Image.new("RGB", (400, 400), (10, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        report = analyze_image(
            buf.getvalue(), declared_content_type="image/jpeg", filename="s.jpg"
        )
        self.assertEqual(_verdict(report, "format"), "attention")

    def test_corrupt_bytes_flagged_not_crashing(self) -> None:
        report = analyze_image(b"this is not an image", declared_content_type="image/jpeg")
        self.assertEqual(_verdict(report, "decodable"), "attention")
        self.assertEqual(report["overall"], "attention")
        self.assertTrue(report["sha256"])  # still hashable

    def test_same_image_same_phash(self) -> None:
        data = _jpeg()
        r1 = analyze_image(data, declared_content_type="image/jpeg")
        r2 = analyze_image(data, declared_content_type="image/jpeg")
        self.assertEqual(r1["phash"], r2["phash"])
        self.assertEqual(r1["sha256"], r2["sha256"])
