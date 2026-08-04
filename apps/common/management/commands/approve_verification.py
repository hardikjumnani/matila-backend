"""DEV: approve a user's verification so they reach GO_HOME."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.users.enums import AccountStatus, VerificationStatus

from ._harness import ensure_dev, get_user


class Command(BaseCommand):
    help = "DEV: approve a user's verification (moves them toward GO_HOME)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--email", required=True, help="User's college email.")

    def handle(self, *args, **options) -> None:
        ensure_dev()
        user = get_user(options["email"])
        user.verification_status = VerificationStatus.APPROVED
        user.verified_at = timezone.now()
        user.account_status = AccountStatus.ACTIVE
        user.save(
            update_fields=["verification_status", "verified_at", "account_status"]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Approved {user.college_email} → "
                f"verification_status={user.verification_status}"
            )
        )
