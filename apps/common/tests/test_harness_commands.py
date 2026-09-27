"""Tests for the dev-only harness management commands."""

from __future__ import annotations

import uuid
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat
from apps.messaging.models import Message
from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User

DEV = override_settings(DEBUG=True)


def _owner() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email="owner@college.edu",
        full_name="Owner",
        gender=Gender.MALE,
        intent=Intent.RELATIONSHIP,
        gender_preferences=[Gender.FEMALE],
        onboarding_completed_at=timezone.now(),
        verification_status=VerificationStatus.APPROVED,
        verified_at=timezone.now(),
    )


class HarnessCommandTests(TestCase):
    def setUp(self) -> None:
        self.owner = _owner()

    def _partner_of(self, chat: Chat) -> User:
        return chat.participants.exclude(user=self.owner).get().user

    @DEV
    def test_seed_partner_chat_mode_creates_compatible_chat(self) -> None:
        call_command("seed_partner", "--for-email", self.owner.college_email)
        chat = Chat.objects.filter(participants__user=self.owner).get()
        self.assertEqual(chat.status, ChatStatus.ACTIVE)
        partner = self._partner_of(chat)
        self.assertEqual(partner.verification_status, VerificationStatus.APPROVED)
        # Compatible with the owner's hard filters.
        self.assertEqual(partner.intent, self.owner.intent)
        self.assertIn(partner.gender, self.owner.gender_preferences)
        self.assertIn(self.owner.gender, partner.gender_preferences)

    @DEV
    def test_send_as_delivers_message(self) -> None:
        call_command("seed_partner", "--for-email", self.owner.college_email)
        chat = Chat.objects.filter(participants__user=self.owner).get()
        partner = self._partner_of(chat)
        call_command(
            "send_as",
            "--as",
            partner.college_email,
            "--chat",
            str(chat.id),
            "--text",
            "hello from the partner",
        )
        message = Message.objects.get(chat=chat)
        self.assertEqual(message.sender_id, partner.id)
        self.assertEqual(message.text_content, "hello from the partner")

    @DEV
    def test_approve_verification(self) -> None:
        self.owner.verification_status = VerificationStatus.PENDING
        self.owner.save(update_fields=["verification_status"])
        call_command("approve_verification", "--email", self.owner.college_email)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.verification_status, VerificationStatus.APPROVED)
        self.assertIsNotNone(self.owner.verified_at)

    @DEV
    def test_expire_chat(self) -> None:
        call_command("seed_partner", "--for-email", self.owner.college_email)
        chat = Chat.objects.filter(participants__user=self.owner).get()
        call_command("expire_chat", "--chat", str(chat.id))
        chat.refresh_from_db()
        self.assertEqual(chat.status, ChatStatus.EXPIRED)

    @DEV
    def test_seed_partner_requires_onboarded_owner(self) -> None:
        self.owner.onboarding_completed_at = None
        self.owner.save(update_fields=["onboarding_completed_at"])
        with self.assertRaises(CommandError):
            call_command("seed_partner", "--for-email", self.owner.college_email)

    def test_commands_refuse_without_debug(self) -> None:
        # Test settings run with DEBUG=False; the dev guard must block.
        with self.assertRaises(CommandError):
            call_command(
                "approve_verification",
                "--email",
                self.owner.college_email,
                stdout=StringIO(),
            )
