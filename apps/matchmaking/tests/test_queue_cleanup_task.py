"""Tests for the cleanup_stale_match_queue scheduled task."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from apps.matchmaking.enums import MatchQueueStatus
from apps.matchmaking.models import MatchQueue
from apps.matchmaking.tasks.queue_cleanup import cleanup_stale_match_queue
from apps.users.enums import Intent
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class CleanupStaleMatchQueueTests(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_times_out_stale_entries(self) -> None:
        entry = MatchQueue.objects.create(
            user=_user(),
            intent=Intent.FRIENDSHIP,
            status=MatchQueueStatus.SEARCHING,
            last_heartbeat_at=timezone.now() - timedelta(hours=1),
        )
        fresh = MatchQueue.objects.create(
            user=_user(),
            intent=Intent.FRIENDSHIP,
            status=MatchQueueStatus.SEARCHING,
            last_heartbeat_at=timezone.now(),
        )

        removed = cleanup_stale_match_queue()

        self.assertEqual(removed, 1)
        entry.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(entry.status, MatchQueueStatus.TIMEOUT)
        self.assertEqual(fresh.status, MatchQueueStatus.SEARCHING)
