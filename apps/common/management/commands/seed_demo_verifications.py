"""DEV: seed dummy PENDING verification applications (with images) for the admin panel."""

from __future__ import annotations

import io
import struct
import uuid
import zlib

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.common.management.commands._harness import ensure_dev
from apps.common.services.storage_service import StorageService
from apps.users.enums import AccountStatus, Gender, Intent, VerificationStatus
from apps.users.models import User
from apps.verification.models import VerificationRequest

_NAMES = ["Riya Sharma", "Arjun Mehta", "Neha Gupta", "Karan Singh", "Ananya Rao"]
_GESTURES = ["THUMBS_UP", "PEACE_SIGN", "OPEN_PALM", "WAVE"]
_COLORS = [(66, 135, 245), (46, 204, 113), (241, 196, 15), (231, 76, 60), (155, 89, 182)]


def _png(w: int, h: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress((b"\x00" + bytes(rgb) * w) * h, 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


class Command(BaseCommand):
    help = "DEV: seed dummy PENDING verification applications (with dummy images)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--count", type=int, default=4)

    def handle(self, *args, **options) -> None:
        ensure_dev()
        storage = StorageService()
        created = 0
        for i in range(options["count"]):
            name = _NAMES[i % len(_NAMES)]
            gender = Gender.FEMALE if i % 2 == 0 else Gender.MALE
            user = User.objects.create(
                firebase_uid="demo_verif_" + uuid.uuid4().hex,
                college_email=f"demo.applicant.{uuid.uuid4().hex[:8]}@college.edu",
                full_name=name,
                gender=gender,
                intent=Intent.RELATIONSHIP,
                gender_preferences=[
                    Gender.MALE if gender == Gender.FEMALE else Gender.FEMALE
                ],
                verification_status=VerificationStatus.PENDING,
                account_status=AccountStatus.ACTIVE,
                onboarding_completed_at=timezone.now(),
            )
            color = _COLORS[i % len(_COLORS)]
            id_key = storage.build_key("verification/college-id", "id.png")
            storage.upload_fileobj(
                io.BytesIO(_png(480, 300, color)), id_key, content_type="image/png"
            )
            selfie_key = storage.build_key("verification/selfie", "selfie.png")
            storage.upload_fileobj(
                io.BytesIO(_png(360, 360, color)), selfie_key, content_type="image/png"
            )
            VerificationRequest.objects.create(
                user=user,
                attempt_number=1,
                status=VerificationStatus.PENDING,
                gesture_type=_GESTURES[i % len(_GESTURES)],
                college_id_image_url=id_key,
                gesture_selfie_image_url=selfie_key,
                submitted_at=timezone.now(),
            )
            created += 1
            self.stdout.write(self.style.SUCCESS(f"  seeded {name} ({user.college_email})"))
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {created} PENDING verification application(s).")
        )
