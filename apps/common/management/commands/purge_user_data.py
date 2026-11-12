"""Management command: wipe ALL user/account data for a clean launch.

DESTRUCTIVE and irreversible. Take a backup first (see ``backup_database``).

Deletes every account and all transactional data in one transaction, leaf-to-root
so the PROTECT foreign keys (payments / ratings / reports reference users and
chats with PROTECT) are cleared before their targets. KEEPS reference and config
data: ``colleges``, ``app_config`` and ``feature_flags`` (so PRICING and feature
flags survive), plus the Django admin/auth tables. Admins are an email allow-list
(``ADMIN_EMAILS``), not a DB row, so wiping all app accounts does not remove admin
access: an admin simply signs in again and their user row is recreated.

Does NOT touch Redis or blob storage (handled separately in the wipe runbook).

Usage:
    manage.py purge_user_data --dry-run        # print counts, delete nothing
    manage.py purge_user_data --confirm WIPE   # actually delete
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditLog
from apps.chats.models import Chat, ChatParticipant
from apps.colleges.models import College, LaunchNotification
from apps.configuration.models import AppConfig, FeatureFlag
from apps.matchmaking.models import MatchQueue
from apps.messaging.models import Message, MessageReaction
from apps.notifications.models import DeviceToken, Notification
from apps.payments.models import CoinLedger, Payment, Wallet
from apps.privacy.models import (
    LeakEvent,
    LeakStrike,
    ProfanityEvent,
    SuspicionEvent,
    UserSuspicionProfile,
)
from apps.ratings.models import Rating
from apps.reports.models import Report
from apps.reveal.models import DecisionRound, ParticipantDecision
from apps.users.models import BlockedName, User
from apps.verification.models import VerificationRequest

CONFIRM_TOKEN = "WIPE"

# Leaf-to-root. PROTECT holders (coin_ledger/payments/wallets/ratings/reports)
# come before their targets (users, chats, payments, wallets); chat-scoped rows
# before chats; everything user-scoped before users; sessions last.
PURGE_ORDER = [
    CoinLedger,
    Payment,
    Wallet,
    Rating,
    Report,
    MessageReaction,
    Message,
    ParticipantDecision,
    DecisionRound,
    ChatParticipant,
    Chat,
    MatchQueue,
    LeakStrike,
    SuspicionEvent,
    ProfanityEvent,
    LeakEvent,
    UserSuspicionProfile,
    Notification,
    DeviceToken,
    VerificationRequest,
    BlockedName,
    LaunchNotification,
    AuditLog,
    User,
    Session,
]

# Must be unchanged by the purge (pricing lives in app_config / feature_flags).
KEEP_MODELS = [College, AppConfig, FeatureFlag]


class Command(BaseCommand):
    help = "Wipe all user/account data for a clean launch (keeps colleges, config and pricing)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--confirm",
            default="",
            help=f"Pass '{CONFIRM_TOKEN}' to actually delete (ignored with --dry-run).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print the row counts that would be deleted; delete nothing.",
        )

    def handle(self, *args, **options) -> None:
        dry_run = options["dry_run"]
        confirm = options["confirm"]
        if not dry_run and confirm != CONFIRM_TOKEN:
            raise CommandError(
                f"Refusing to delete without confirmation. Re-run with "
                f"--confirm {CONFIRM_TOKEN} (or --dry-run to preview)."
            )

        # Preserve admin login identities (ADMIN_EMAILS) so a wipe never locks
        # admins out. Admins sign in with non-college emails that bootstrap can't
        # recreate, so their user row must survive. Only the row is kept; their
        # transactional data is wiped like everyone else's.
        admin_emails = {e.strip().lower() for e in settings.ADMIN_EMAILS if e.strip()}
        preserved_ids = [
            uid
            for uid, email in User.objects.values_list("id", "college_email")
            if (email or "").lower() in admin_emails
        ]

        keep_before = {m.__name__: m.objects.count() for m in KEEP_MODELS}

        self.stdout.write("Rows to purge:")
        total = 0
        for model in PURGE_ORDER:
            count = model.objects.count()
            if model is User:
                count -= len(preserved_ids)
            total += count
            self.stdout.write(f"  {model._meta.db_table:24s} {count}")
        self.stdout.write(f"  {'TOTAL':24s} {total}")
        if preserved_ids:
            self.stdout.write(
                f"Preserving {len(preserved_ids)} admin account(s): "
                + ", ".join(sorted(admin_emails))
            )
        else:
            self.stdout.write("Preserving 0 admin accounts.")
        self.stdout.write(
            "Keeping (must be unchanged): "
            + ", ".join(f"{k}={v}" for k, v in keep_before.items())
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing deleted."))
            return

        with transaction.atomic():
            for model in PURGE_ORDER:
                if model is User:
                    User.objects.exclude(id__in=preserved_ids).delete()
                else:
                    model.objects.all().delete()

            # Verify inside the transaction so any surprise rolls everything back.
            # Only the preserved admin rows may remain in `users`.
            leftover = {}
            for m in PURGE_ORDER:
                remaining = m.objects.count()
                allowed = len(preserved_ids) if m is User else 0
                if remaining != allowed:
                    leftover[m._meta.db_table] = remaining
            if leftover:
                raise CommandError(f"Purge incomplete, rolling back: {leftover}")
            keep_after = {m.__name__: m.objects.count() for m in KEEP_MODELS}
            if keep_after != keep_before:
                raise CommandError(
                    f"KEEP tables changed, rolling back: "
                    f"before={keep_before} after={keep_after}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Purge complete. Wiped all accounts and transactional data "
                f"(kept {len(preserved_ids)} admin login(s)); "
                "colleges, config and pricing preserved."
            )
        )
