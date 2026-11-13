"""Provision (or refresh) the isolated App Store reviewer demo account.

Idempotent and prod-safe (unlike the DEBUG-gated test harness). Ensures:
  - the Firebase Auth user (uid + verified email) behind the custom token,
  - the matila demo ``User`` row (launched college, onboarded, APPROVED, is_demo),
  - a pre-granted coin balance,
  - a demo partner (is_demo) + one active anonymous chat with a seed message,
    so the app is alive end-to-end for the reviewer.

The demo account matches ONLY with other demo accounts and is excluded from
every real-user-facing count (see matchmaking_service). Pairs with the
``POST /auth/review-login`` endpoint, which mints the custom token. AI_BRIDGE [00079].

Usage:
    manage.py provision_review_account                  # settings defaults
    manage.py provision_review_account --coins 100
    manage.py provision_review_account --skip-firebase  # DB-only refresh
"""

from __future__ import annotations

import datetime
import io
import struct
import uuid
import zlib

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.users.enums import AccountStatus, Gender, Intent, VerificationStatus
from apps.users.models import User

_PARTNER_UID = "matila-review-demo-partner"
_PARTNER_EMAIL = "appreview.partner@matila.demo"


def _solid_png(w: int, h: int, rgb: tuple[int, int, int]) -> bytes:
    """A tiny solid-colour PNG, built with the stdlib (PIL is not on prod)."""

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # RGB, 8-bit
    row = b"\x00" + bytes(rgb) * w
    idat = zlib.compress(row * h, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


class Command(BaseCommand):
    help = "Provision/refresh the isolated App Store reviewer demo account (idempotent)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--coins", type=int, default=100)
        parser.add_argument("--name", default="Jordan (Demo)")
        parser.add_argument("--partner-name", default="Riley (Demo)")
        parser.add_argument(
            "--skip-firebase",
            action="store_true",
            help="Do not create/update the Firebase Auth user (DB-only refresh).",
        )

    def handle(self, *args, **options) -> None:
        uid = (settings.REVIEW_DEMO_UID or "").strip()
        email = (settings.REVIEW_DEMO_EMAIL or "").strip()
        if not uid or not email:
            raise CommandError("REVIEW_DEMO_UID and REVIEW_DEMO_EMAIL must be set.")

        # 1. Firebase Auth user — so a signInWithCustomToken session carries a
        #    verified `email` claim (the session bootstrap requires one).
        if not options["skip_firebase"]:
            from apps.common.firebase import ensure_auth_user

            ensure_auth_user(uid, email)
            self.stdout.write(f"Firebase auth user ensured: {uid} <{email}>")

        college = self._launched_college()

        # 2. Demo user + demo partner rows (both isolated, mutually compatible).
        user = self._upsert_demo_user(
            uid=uid,
            email=email,
            college=college,
            name=options["name"],
            rgb=(255, 95, 162),
        )
        partner = self._upsert_demo_user(
            uid=_PARTNER_UID,
            email=_PARTNER_EMAIL,
            college=college,
            name=options["partner_name"],
            rgb=(95, 162, 255),
        )

        # 3. Pre-grant coins (top up to target; re-grants after a wipe).
        self._topup_coins(user, target=options["coins"])

        # 4. Seed one active anonymous chat with a welcome message.
        chat_id = self._seed_chat(user, partner)

        code_state = "SET" if (settings.REVIEW_LOGIN_CODE or "").strip() else "UNSET"
        self.stdout.write(self.style.SUCCESS("Review demo account provisioned."))
        self.stdout.write(f"  demo user   : {user.college_email}  id={user.id}")
        self.stdout.write(f"  demo uid    : {uid}")
        self.stdout.write(f"  college     : {college.code} (launched={college.is_launched})")
        self.stdout.write(f"  coins       : {options['coins']}")
        self.stdout.write(f"  seed chat   : {chat_id or '(existing/none)'}")
        self.stdout.write(f"  REVIEW_LOGIN_CODE: {code_state}")

    # -- steps --------------------------------------------------------------

    def _launched_college(self):
        """A launched college to park the demo accounts on. UNASSIGNED is the
        designated catch-all for seed/test accounts (launched since 2000); fall
        back to any launched college if it is somehow missing."""
        from apps.colleges.models import College
        from apps.colleges.services.college_service import UNASSIGNED_CODE

        college = College.objects.filter(code=UNASSIGNED_CODE).first()
        if college is None:
            college = next(
                (c for c in College.objects.all() if c.is_launched), None
            )
        if college is None:
            raise CommandError("No launched college available for the demo account.")
        return college

    def _upsert_demo_user(self, *, uid, email, college, name, rgb) -> User:
        user, _ = User.objects.get_or_create(
            firebase_uid=uid, defaults={"college_email": email}
        )
        user.college_email = email
        user.college = college
        user.full_name = name
        user.gender = Gender.OTHER
        user.intent = Intent.FRIENDSHIP  # unlimited (not relationship-capped)
        user.gender_preferences = []  # any gender, so demo <-> demo always matches
        if user.date_of_birth is None:
            user.date_of_birth = datetime.date(2000, 1, 1)
        user.verification_status = VerificationStatus.APPROVED
        user.verified_at = user.verified_at or timezone.now()
        user.account_status = AccountStatus.ACTIVE
        user.onboarding_completed_at = user.onboarding_completed_at or timezone.now()
        user.is_demo = True
        if not user.profile_photo_url:
            self._set_photo(user, rgb)
        user.save()
        return user

    def _set_photo(self, user: User, rgb) -> None:
        """Best-effort avatar upload (never fail provisioning on storage)."""
        try:
            from apps.common.services.storage_service import StorageService

            storage = StorageService()
            key = storage.build_key("profile-photos", "demo.png")
            storage.upload_fileobj(
                io.BytesIO(_solid_png(256, 256, rgb)), key, content_type="image/png"
            )
            user.profile_photo_url = key
        except Exception as exc:  # noqa: BLE001 — avatar is nice-to-have.
            self.stderr.write(f"  (avatar upload skipped: {exc!r})")

    def _topup_coins(self, user: User, *, target: int) -> None:
        from apps.payments.enums import CoinLedgerReason
        from apps.payments.services.credit_service import CreditService

        credits = CreditService()
        balance = credits.get_balances(user)["coins"]
        if balance >= target:
            return
        credits.credit(
            user=user,
            amount=target - balance,
            reason=CoinLedgerReason.ADMIN_ADJUST,
            idempotency_key=f"review-demo-topup:{user.id}:{uuid.uuid4().hex}",
            note="Reviewer demo account coin top-up",
        )

    def _seed_chat(self, user: User, partner: User):
        from apps.chats.services.chat_service import ChatService
        from apps.messaging.services.message_service import MessageService

        chats = ChatService()
        if chats.get_open_anonymous_chat(user) is not None:
            return None
        result = chats.create_chat(user, partner, intent=Intent.FRIENDSHIP)
        if result.failed:
            self.stderr.write(f"  (seed chat skipped: {result.error_message})")
            return None
        chat = result.data
        try:
            MessageService().send_text(
                chat_id=str(chat.id),
                sender=partner,
                content="Hey! Welcome to Matila. Tap around and say hi 👋",
            )
        except Exception as exc:  # noqa: BLE001 — broadcast/push is best-effort.
            self.stderr.write(f"  (seed message skipped: {exc!r})")
        return chat.id
