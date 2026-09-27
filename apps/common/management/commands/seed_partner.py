"""DEV: create a verified partner compatible with an owner, and pair them."""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.users.enums import AccountStatus, Gender, Intent, VerificationStatus
from apps.users.models import User

from ._harness import ensure_dev, get_user

_ALL_GENDERS = [Gender.MALE, Gender.FEMALE, Gender.OTHER]


class Command(BaseCommand):
    help = "DEV: create a verified partner compatible with an owner, and pair them."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--for-email",
            required=True,
            help="Owner's college email (must have completed onboarding).",
        )
        parser.add_argument(
            "--mode",
            choices=["chat", "queue"],
            default="chat",
            help="chat: create the anonymous chat directly (default). "
            "queue: put the partner in matchmaking so the owner can 'find match'.",
        )
        parser.add_argument("--name", default="Alex Partner")

    def handle(self, *args, **options) -> None:
        ensure_dev()
        owner = get_user(options["for_email"])
        if owner.onboarding_completed_at is None:
            raise CommandError(
                "Owner has not completed onboarding; finish onboarding in the app "
                "first so the partner can be made compatible."
            )

        # Build a profile that satisfies the matchmaking hard filters: same
        # intent, and mutual gender-preference satisfaction.
        partner_gender = (owner.gender_preferences or _ALL_GENDERS)[0]
        partner = User.objects.create(
            firebase_uid="dev_partner_" + uuid.uuid4().hex,
            college_email=f"demo.partner.{uuid.uuid4().hex[:8]}@dev.local",
            full_name=options["name"],
            gender=partner_gender,
            intent=owner.intent or Intent.RELATIONSHIP,
            gender_preferences=[owner.gender] if owner.gender else list(_ALL_GENDERS),
            verification_status=VerificationStatus.APPROVED,
            verified_at=timezone.now(),
            account_status=AccountStatus.ACTIVE,
            onboarding_completed_at=timezone.now(),
        )

        if options["mode"] == "chat":
            from apps.chats.services.chat_service import ChatService

            result = ChatService().create_chat(owner, partner)
            if result.failed:
                raise CommandError(f"create_chat failed: {result.error_message}")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Partner {partner.college_email} created; "
                    f"anonymous chat {result.data.id} ready (owner <-> partner)."
                )
            )
            self.stdout.write(f"chat_id={result.data.id}")
        else:
            from apps.matchmaking.services.matchmaking_service import MatchmakingService

            mm = MatchmakingService()
            result = mm.join(partner)
            if result.failed:
                raise CommandError(f"partner join failed: {result.error_message}")
            # Mark the partner online so the owner's join can pair with them.
            mm.heartbeat(partner)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Partner {partner.college_email} created and waiting in "
                    "matchmaking -- have the owner tap 'find match' to pair."
                )
            )

        self.stdout.write(
            f"partner_email={partner.college_email}  partner_id={partner.id}"
        )
