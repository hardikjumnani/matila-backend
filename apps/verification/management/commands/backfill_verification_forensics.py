"""Backfill image forensics for existing verification requests.

Re-downloads each stored gesture selfie / college ID, runs the (report-only)
forensic analysis, and saves the report + hashes so the admin panel shows the
report on historical verifications too. Idempotent and safe to re-run; per-image
failures are logged and skipped (never aborts the batch). AI_BRIDGE / EXTERNAL.

Usage:
    manage.py backfill_verification_forensics --dry-run
    manage.py backfill_verification_forensics            # only missing reports
    manage.py backfill_verification_forensics --all      # recompute everything
    manage.py backfill_verification_forensics --status PENDING --limit 500
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.verification.models import VerificationRequest

# (image key, forensics field, sha field, phash field)
_IMAGES = [
    ("gesture_selfie_image_url", "gesture_selfie_forensics", "selfie_sha256", "selfie_phash"),
    ("college_id_image_url", "college_id_forensics", "college_id_sha256", "college_id_phash"),
]


class Command(BaseCommand):
    help = "Backfill report-only image forensics for existing verification requests."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--all", action="store_true",
                            help="Recompute even when a report already exists.")
        parser.add_argument("--status", default="",
                            help="Only this verification status (e.g. PENDING).")
        parser.add_argument("--limit", type=int, default=0,
                            help="Cap the number of requests processed (0 = no cap).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be processed; write nothing.")

    def handle(self, *args, **options) -> None:
        from apps.common.services.storage_service import StorageService
        from apps.verification.services.image_forensics import analyze_image

        storage = StorageService()
        qs = VerificationRequest.objects.all().order_by("-created_at")
        if options["status"]:
            qs = qs.filter(status=options["status"].upper())
        if options["limit"]:
            qs = qs[: options["limit"]]

        do_all = options["all"]
        dry = options["dry_run"]
        processed = skipped = errors = images_done = 0

        for req in qs:
            changed: list[str] = []
            touched = False
            for key_attr, forensics_attr, sha_attr, phash_attr in _IMAGES:
                key = getattr(req, key_attr)
                if not key:
                    continue
                if not do_all and getattr(req, forensics_attr):
                    continue  # already has a report
                touched = True
                if dry:
                    images_done += 1
                    continue
                try:
                    data, content_type = storage.download_bytes(key)
                    report = analyze_image(
                        data, declared_content_type=content_type,
                        reference_time=req.created_at,
                    )
                except Exception as exc:  # noqa: BLE001 — never abort the batch.
                    errors += 1
                    self.stderr.write(f"  {req.id} {key_attr}: {exc!r}")
                    continue
                setattr(req, forensics_attr, report)
                setattr(req, sha_attr, report.get("sha256", ""))
                setattr(req, phash_attr, report.get("phash", ""))
                changed += [forensics_attr, sha_attr, phash_attr]
                images_done += 1
            if touched:
                processed += 1
            else:
                skipped += 1
            if changed and not dry:
                req.save(update_fields=changed + ["updated_at"])

        verb = "Would process" if dry else "Processed"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {processed} request(s), {images_done} image(s); "
            f"skipped {skipped} (nothing to do); {errors} error(s)."
        ))
