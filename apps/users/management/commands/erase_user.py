"""
Erase all personal data for a user (DPDP / GDPR right to erasure).

Run by an admin on a verified deletion request (e.g. arriving at the published
privacy contact email). Irreversible.

    python manage.py erase_user --email someone@college.edu
    python manage.py erase_user --user-id <uuid> --yes --by ops@matila.in
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.users.enums import AccountStatus
from apps.users.models import User
from apps.users.services.erasure_service import UserErasureService


class Command(BaseCommand):
    help = "Erase all personal data for a user, by --email or --user-id (irreversible)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--email", help="college_email of the user to erase.")
        parser.add_argument("--user-id", help="UUID of the user to erase.")
        parser.add_argument(
            "--by", default="admin", help="Who ran the erasure (recorded in the audit log)."
        )
        parser.add_argument(
            "--yes", action="store_true", help="Skip the interactive confirmation prompt."
        )

    def handle(self, *args, **options) -> None:
        email = options.get("email")
        user_id = options.get("user_id")
        if not email and not user_id:
            raise CommandError("Provide --email or --user-id.")

        if email:
            user = User.objects.filter(college_email__iexact=email).first()
        else:
            user = User.objects.filter(id=user_id).first()
        if user is None:
            raise CommandError("No matching user found.")

        if user.account_status == AccountStatus.DELETED or user.college_email.startswith(
            "erased-"
        ):
            self.stdout.write(self.style.WARNING("User already appears erased; continuing."))

        label = f"{user.id} ({user.college_email})"
        if not options["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    f"This will PERMANENTLY erase all personal data for user {label}."
                )
            )
            confirm = input("Type the user's email to confirm: ").strip()
            if confirm != user.college_email:
                raise CommandError("Confirmation did not match; aborted.")

        summary = UserErasureService().erase(user, requested_by=options["by"])
        self.stdout.write(self.style.SUCCESS(f"Erased user {label}:"))
        for key, value in summary.items():
            self.stdout.write(f"  {key}: {value}")
