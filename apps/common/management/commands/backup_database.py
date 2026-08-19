"""
Management command: back up the PostgreSQL database to Azure Blob Storage.

Runs ``pg_dump`` (custom/compressed format) and uploads the dump to the private
``backups`` container in the prod storage account. Scheduled nightly by a systemd
timer (``matila-backup.timer``); 14-day retention is enforced by a Blob lifecycle
rule. The restore procedure lives in ``docs/RESTORE.md``.

Redis is intentionally NOT backed up — it is an ephemeral cache / broker /
channel layer and is rebuilt from scratch on restore.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

BACKUP_CONTAINER = "backups"


class Command(BaseCommand):
    help = "pg_dump the database and upload the dump to Azure Blob Storage."

    def handle(self, *args, **options) -> None:
        if not settings.AZURE_STORAGE_CONNECTION_STRING:
            raise CommandError("AZURE_STORAGE_CONNECTION_STRING is not configured.")

        db = settings.DATABASES["default"]
        name = db.get("NAME") or ""
        stamp = timezone.now().strftime("%Y%m%d-%H%M%SZ")
        blob_name = f"{name}-{stamp}.dump"

        # Password goes via PGPASSWORD (env), never argv, so it can't leak via `ps`.
        env = {**os.environ, "PGPASSWORD": str(db.get("PASSWORD") or "")}
        pg_dump_cmd = [
            "pg_dump",
            "-Fc",  # custom (compressed) format -> restore with pg_restore
            "--no-password",
            "-h", str(db.get("HOST") or "localhost"),
            "-p", str(db.get("PORT") or "5432"),
            "-U", str(db.get("USER") or ""),
            "-d", name,
        ]

        with tempfile.TemporaryDirectory() as tmp:
            dump_path = Path(tmp) / blob_name
            self.stdout.write(f"Running pg_dump -> {dump_path.name} ...")
            try:
                subprocess.run(
                    [*pg_dump_cmd, "-f", str(dump_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                )
            except FileNotFoundError as exc:
                raise CommandError("pg_dump not found on PATH.") from exc
            except subprocess.CalledProcessError as exc:
                self._report_failure(f"pg_dump: {exc.stderr}")
                raise CommandError(f"pg_dump failed (exit {exc.returncode}).") from exc

            size = dump_path.stat().st_size
            if size == 0:
                raise CommandError("pg_dump produced an empty file.")

            self.stdout.write(
                f"Uploading {blob_name} ({size} bytes) to '{BACKUP_CONTAINER}' ..."
            )
            try:
                from azure.storage.blob import BlobServiceClient

                svc = BlobServiceClient.from_connection_string(
                    settings.AZURE_STORAGE_CONNECTION_STRING
                )
                container = svc.get_container_client(BACKUP_CONTAINER)
                try:
                    container.create_container()
                except Exception:  # noqa: BLE001 — container already exists.
                    pass
                with dump_path.open("rb") as fh:
                    container.upload_blob(name=blob_name, data=fh, overwrite=True)
            except Exception as exc:  # noqa: BLE001
                self._report_failure(f"blob upload: {exc}")
                raise CommandError(f"Upload to Blob failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Backup uploaded: {BACKUP_CONTAINER}/{blob_name} ({size} bytes)"
            )
        )

    def _report_failure(self, detail: str) -> None:
        """Best-effort Sentry alert; a failed backup must be visible."""
        try:
            import sentry_sdk
        except ImportError:
            return
        sentry_sdk.capture_message(f"Database backup failed: {detail[:500]}", level="error")
