"""
Matchmaking concurrency test — validates FOR UPDATE SKIP LOCKED on PostgreSQL.

Two users join simultaneously, both compatible with the same waiting user. With
row-level SKIP LOCKED, exactly one may claim the waiting user, so exactly one
chat is created. This is the behavior SQLite cannot exercise (its locks are
no-ops), so the test is skipped on non-PostgreSQL backends.
"""

from __future__ import annotations

import threading
import uuid
from unittest import skipUnless

from django.db import connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from apps.chats.models import Chat
from apps.matchmaking.services.matchmaking_service import MatchmakingService
from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User


def _eligible(gender: str, prefs: list[str]) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        gender=gender,
        intent=Intent.RELATIONSHIP,
        gender_preferences=prefs,
        verification_status=VerificationStatus.APPROVED,
        onboarding_completed_at=timezone.now(),
    )


@skipUnless(
    connection.vendor == "postgresql",
    "SKIP LOCKED row locking is only meaningful on PostgreSQL.",
)
class MatchmakingConcurrencyTests(TransactionTestCase):
    def test_concurrent_joins_produce_exactly_one_chat(self) -> None:
        # Waiting user compatible with both contenders; the two contenders are
        # NOT compatible with each other, so the only possible match is with W.
        waiting = _eligible(Gender.OTHER, [Gender.MALE, Gender.FEMALE])
        contender_a = _eligible(Gender.MALE, [Gender.OTHER])
        contender_b = _eligible(Gender.FEMALE, [Gender.OTHER])

        MatchmakingService().join(waiting)  # W is now searching.

        results: dict = {}
        start = threading.Barrier(2)

        def _join(user: User) -> None:
            start.wait()  # Maximize overlap to actually contend for W's row.
            try:
                results[user.id] = MatchmakingService().join(user)
            finally:
                connections.close_all()  # Close this thread's DB connection.

        threads = [
            threading.Thread(target=_join, args=(contender_a,)),
            threading.Thread(target=_join, args=(contender_b,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # SKIP LOCKED guarantees only one contender claims W.
        self.assertEqual(Chat.objects.count(), 1)
        matched = [
            uid
            for uid, result in results.items()
            if result.success and result.data.matched
        ]
        self.assertEqual(len(matched), 1)
