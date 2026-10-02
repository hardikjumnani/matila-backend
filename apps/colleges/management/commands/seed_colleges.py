"""
Seed the pilot colleges and (optionally) re-resolve existing users onto them.

Idempotent: re-running updates names/domains but never clobbers a deliberately
set ``launch_date`` unless ``--reset-launch`` is given. Real pilot colleges are
always seeded; the DEMO college (which maps common test domains) is added only
with ``--demo`` so those permissive domains never reach production by accident.

Examples:
    # Prod-ish: create pilot colleges, launching in 7 days, don't touch users.
    python manage.py seed_colleges

    # Local: add the demo/test college and move existing users onto their college.
    python manage.py seed_colleges --demo --reassign --launch-in-days 3
"""

from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.colleges.models import College
from apps.colleges.services.college_service import (
    UNASSIGNED_CODE,
    CollegeService,
    domain_of,
)

# The catch-all college is "launched since forever" so legacy/seed/test accounts
# parked on it are never launch-gated. Mirrors users.models._default_college_id.
_UNASSIGNED_LAUNCH = datetime(2000, 1, 1, tzinfo=dt_timezone.utc)

# (code, name, [email domains]) for the real pilot colleges.
_PILOT_COLLEGES: list[tuple[str, str, list[str]]] = [
    ("BITS_PILANI", "BITS Pilani", ["online.bits-pilani.ac.in", "pilani.bits-pilani.ac.in"]),
    ("SCALER", "Scaler School of Technology", ["sst.scaler.com"]),
]

# The demo/test college — only seeded with --demo. Maps the domains used across
# local testing and the dev harness. Never seed these in production.
_DEMO_COLLEGE = (
    "DEMO",
    "Demo College",
    ["college.edu", "dev.local", "matila.in", "gmail.com", "example.com"],
)


class Command(BaseCommand):
    help = "Seed pilot colleges and optionally re-resolve users onto them."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--launch-in-days",
            type=float,
            default=7.0,
            help="Launch offset (days from now) for newly-created colleges.",
        )
        parser.add_argument(
            "--demo",
            action="store_true",
            help="Also seed the DEMO college mapping common test domains.",
        )
        parser.add_argument(
            "--demo-launch-in-minutes",
            type=float,
            default=90.0,
            help="Launch offset (minutes from now) for the DEMO college.",
        )
        parser.add_argument(
            "--reset-launch",
            action="store_true",
            help="Overwrite launch_date on colleges that already exist.",
        )
        parser.add_argument(
            "--reassign",
            action="store_true",
            help="Re-resolve existing users' colleges from their email domain.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        now = timezone.now()
        reset = options["reset_launch"]

        # Ensure the catch-all exists and stays "launched" (ungated).
        unassigned, _ = College.objects.get_or_create(
            code=UNASSIGNED_CODE,
            defaults={
                "name": "Unassigned",
                "allowed_email_domains": [],
                "is_active": False,
                "launch_date": _UNASSIGNED_LAUNCH,
            },
        )
        if unassigned.launch_date is None:
            unassigned.launch_date = _UNASSIGNED_LAUNCH
            unassigned.save(update_fields=["launch_date"])

        colleges = list(_PILOT_COLLEGES)
        if options["demo"]:
            colleges.append(_DEMO_COLLEGE)

        for code, name, domains in colleges:
            is_demo = code == _DEMO_COLLEGE[0]
            if is_demo:
                launch = now + timedelta(minutes=options["demo_launch_in_minutes"])
            else:
                launch = now + timedelta(days=options["launch_in_days"])
            domains = [d.lower() for d in domains]

            college, created = College.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "allowed_email_domains": domains,
                    "launch_date": launch,
                    "is_active": True,
                },
            )
            if not created:
                college.name = name
                college.allowed_email_domains = domains
                college.is_active = True
                if reset or college.launch_date is None:
                    college.launch_date = launch
                college.save(
                    update_fields=[
                        "name",
                        "allowed_email_domains",
                        "is_active",
                        "launch_date",
                    ]
                )

            self.stdout.write(
                f"{'Created' if created else 'Updated'} {code}: "
                f"{', '.join(domains)} -> launch {college.launch_date:%Y-%m-%d %H:%M %Z}"
            )

        if options["reassign"]:
            self._reassign_users()

    def _reassign_users(self) -> None:
        """Move each user to the college matching their email domain (if any)."""
        from apps.users.models import User

        service = CollegeService()
        moved = 0
        unmatched: dict[str, int] = {}
        for user in User.objects.all().iterator():
            resolved = service.resolve_for_email(user.college_email)
            if resolved is None:
                dom = domain_of(user.college_email) or "(none)"
                unmatched[dom] = unmatched.get(dom, 0) + 1
                continue
            if user.college_id != resolved.id:
                user.college = resolved
                user.save(update_fields=["college", "updated_at"])
                moved += 1
        self.stdout.write(self.style.SUCCESS(f"Reassigned {moved} user(s)."))
        if unmatched:
            summary = ", ".join(f"{d}={n}" for d, n in sorted(unmatched.items()))
            self.stdout.write(
                f"Left on current college (unsupported domain): {summary}"
            )
