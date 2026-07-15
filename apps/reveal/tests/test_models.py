"""Model tests for the reveal domain."""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.chats.models import Chat
from apps.reveal.enums import RevealIntentStatus
from apps.reveal.models import RevealIntent
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class RevealIntentModelTests(TestCase):
    def test_defaults(self) -> None:
        intent = RevealIntent.objects.create(chat=Chat.objects.create(), user=_user())
        self.assertEqual(intent.status, RevealIntentStatus.PENDING)

    def test_unique_intent_per_chat_user(self) -> None:
        chat = Chat.objects.create()
        user = _user()
        RevealIntent.objects.create(chat=chat, user=user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RevealIntent.objects.create(chat=chat, user=user)
