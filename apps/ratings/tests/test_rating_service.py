"""Tests for RatingService (real chat/config services)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.chats.enums import EndReason
from apps.chats.services.chat_service import ChatService
from apps.configuration.services.configuration_service import ConfigurationService
from apps.ratings.models import Rating
from apps.ratings.services.rating_service import RatingService
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class RatingServiceTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.chats = ChatService(notification_service=mock.MagicMock())
        self.service = RatingService(
            chat_service=self.chats, configuration_service=ConfigurationService()
        )
        self.a = _user()
        self.b = _user()
        self.chat = self.chats.create_chat(self.a, self.b).data
        # Default active questionnaire is version "v1".
        self.version = self.service.get_active_questionnaire()["version"]

    def _end_chat(self) -> None:
        self.chats.end_chat(str(self.chat.id), reason=EndReason.USER_EXIT)

    def _submit(self, rater, responses=None):
        return self.service.submit_rating(
            chat_id=str(self.chat.id),
            rater=rater,
            questionnaire_version=self.version,
            responses=responses or {"would_chat_again": "YES"},
        )

    def test_cannot_rate_active_chat(self) -> None:
        self.assertEqual(self._submit(self.a).error_code, "VALIDATION_ERROR")

    def test_submit_after_end(self) -> None:
        self._end_chat()
        result = self._submit(self.a)
        self.assertTrue(result.success)
        self.assertEqual(result.data.rated_user_id, self.b.id)

    def test_stale_version_rejected(self) -> None:
        self._end_chat()
        result = self.service.submit_rating(
            chat_id=str(self.chat.id),
            rater=self.a,
            questionnaire_version="v0-old",
            responses={"would_chat_again": "YES"},
        )
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_invalid_response_value_rejected(self) -> None:
        self._end_chat()
        result = self._submit(self.a, responses={"would_chat_again": "MAYBE"})
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_unknown_question_rejected(self) -> None:
        self._end_chat()
        result = self._submit(self.a, responses={"nope": "YES"})
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_duplicate_rating_conflict(self) -> None:
        self._end_chat()
        self._submit(self.a)
        self.assertEqual(self._submit(self.a).error_code, "CONFLICT")

    def test_both_participants_can_rate(self) -> None:
        self._end_chat()
        self.assertTrue(self._submit(self.a).success)
        self.assertTrue(self._submit(self.b).success)
        self.assertEqual(Rating.objects.filter(chat=self.chat).count(), 2)

    def test_non_participant_forbidden(self) -> None:
        self._end_chat()
        self.assertEqual(self._submit(_user()).error_code, "FORBIDDEN")

    def test_get_status(self) -> None:
        self._end_chat()
        self.assertFalse(
            self.service.get_status(chat_id=str(self.chat.id), user=self.a)["has_rated"]
        )
        self._submit(self.a)
        self.assertTrue(
            self.service.get_status(chat_id=str(self.chat.id), user=self.a)["has_rated"]
        )
