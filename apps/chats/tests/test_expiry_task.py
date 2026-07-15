"""Tests for the expire_chats scheduled task."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat
from apps.chats.services.chat_service import ChatService
from apps.chats.tasks.expiry import expire_chats
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class ExpireChatsTaskTests(TestCase):
    def test_expires_only_due_chats(self) -> None:
        due = ChatService().create_chat(_user(), _user()).data
        not_due = ChatService().create_chat(_user(), _user()).data
        Chat.objects.filter(id=due.id).update(
            current_phase_ends_at=timezone.now() - timedelta(minutes=1)
        )
        Chat.objects.filter(id=not_due.id).update(
            current_phase_ends_at=timezone.now() + timedelta(hours=1)
        )

        expired = expire_chats()

        self.assertEqual(expired, 1)
        due.refresh_from_db()
        not_due.refresh_from_db()
        self.assertEqual(due.status, ChatStatus.EXPIRED)
        self.assertEqual(not_due.status, ChatStatus.ACTIVE)
