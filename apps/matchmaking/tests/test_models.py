"""Model tests for the matchmaking domain."""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.matchmaking.enums import MatchQueueStatus
from apps.matchmaking.models import MatchQueue
from apps.users.enums import Intent
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class MatchQueueModelTests(TestCase):
    def test_only_one_active_entry_per_user(self) -> None:
        user = _user()
        MatchQueue.objects.create(user=user, intent=Intent.RELATIONSHIP)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MatchQueue.objects.create(user=user, intent=Intent.RELATIONSHIP)

    def test_non_active_entries_do_not_block_a_new_search(self) -> None:
        """The partial unique index only constrains SEARCHING rows, so a user
        with a previously cancelled entry can join the queue again."""
        user = _user()
        MatchQueue.objects.create(
            user=user, intent=Intent.CASUAL, status=MatchQueueStatus.CANCELLED
        )
        # Must not raise.
        entry = MatchQueue.objects.create(user=user, intent=Intent.CASUAL)
        self.assertEqual(entry.status, MatchQueueStatus.SEARCHING)
