"""Model tests for the ratings domain."""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.chats.models import Chat
from apps.ratings.models import Rating
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class RatingModelTests(TestCase):
    def test_unique_rating_per_chat_rater(self) -> None:
        chat = Chat.objects.create()
        rater = _user()
        other = _user()
        Rating.objects.create(
            chat=chat, rated_by=rater, rated_user=other, questionnaire_version="v1"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Rating.objects.create(
                chat=chat, rated_by=rater, rated_user=other, questionnaire_version="v1"
            )

    def test_both_participants_can_rate_same_chat(self) -> None:
        chat = Chat.objects.create()
        a, b = _user(), _user()
        Rating.objects.create(
            chat=chat, rated_by=a, rated_user=b, questionnaire_version="v1"
        )
        Rating.objects.create(
            chat=chat, rated_by=b, rated_user=a, questionnaire_version="v1"
        )
        self.assertEqual(Rating.objects.filter(chat=chat).count(), 2)
