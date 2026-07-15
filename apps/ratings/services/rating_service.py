"""
Rating service.

Owns ``ratings`` and reads the active questionnaire from ``app_config``. Ratings
are optional, allowed only after a chat has ended or expired, and limited to one
per chat per user. Answers are validated against the active questionnaire
version and the fixed response value set.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import IntegrityError

from apps.chats.enums import ChatStatus
from apps.chats.models import ChatParticipant
from apps.common.results import ServiceResult
from apps.ratings.enums import RatingResponse
from apps.ratings.models import Rating
from apps.users.models import User

logger = logging.getLogger(__name__)

# Ratings may be submitted only once a chat is terminal.
_RATEABLE_STATUSES = (ChatStatus.ENDED, ChatStatus.EXPIRED)
_MAX_FEEDBACK_LENGTH = 500
_VALID_RESPONSES = set(RatingResponse.values)


class RatingService:
    """Post-chat rating questionnaire and submission."""

    def __init__(self, *, chat_service=None, configuration_service=None) -> None:
        if chat_service is None:
            from apps.chats.services.chat_service import ChatService

            chat_service = ChatService()
        if configuration_service is None:
            from apps.configuration.services.configuration_service import (
                ConfigurationService,
            )

            configuration_service = ConfigurationService()
        self._chats = chat_service
        self._config = configuration_service

    def get_active_questionnaire(self) -> dict[str, Any]:
        """Return the active, backend-driven rating questionnaire."""
        return self._config.get_rating_questionnaire()

    def get_status(self, *, chat_id: str, user: User) -> dict:
        return {
            "has_rated": Rating.objects.filter(chat_id=chat_id, rated_by=user).exists()
        }

    def submit_rating(
        self,
        *,
        chat_id: str,
        rater: User,
        questionnaire_version: str,
        responses: dict[str, str],
        feedback_text: str = "",
    ) -> ServiceResult[Rating]:
        """Store a rating after validating chat state, version, and responses."""
        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        if not self._chats.is_participant(chat, rater):
            return ServiceResult.fail("FORBIDDEN", "You are not in this chat.")
        if chat.status not in _RATEABLE_STATUSES:
            return ServiceResult.fail(
                "VALIDATION_ERROR",
                "Ratings are allowed only after a chat ends or expires.",
            )

        questionnaire = self.get_active_questionnaire()
        active_version = questionnaire.get("version")
        if questionnaire_version != active_version:
            return ServiceResult.fail(
                "VALIDATION_ERROR",
                "Rating questionnaire is out of date; fetch the latest version.",
            )

        validation_error = self._validate_responses(questionnaire, responses)
        if validation_error is not None:
            return validation_error
        if len(feedback_text) > _MAX_FEEDBACK_LENGTH:
            return ServiceResult.fail(
                "VALIDATION_ERROR",
                f"Feedback exceeds {_MAX_FEEDBACK_LENGTH} characters.",
            )

        other = (
            ChatParticipant.objects.select_related("user")
            .filter(chat=chat)
            .exclude(user=rater)
            .first()
        )
        if other is None:
            return ServiceResult.fail(
                "VALIDATION_ERROR", "Chat has no other participant to rate."
            )

        try:
            rating = Rating.objects.create(
                chat=chat,
                rated_by=rater,
                rated_user=other.user,
                questionnaire_version=questionnaire_version,
                responses=responses,
                feedback_text=feedback_text,
            )
        except IntegrityError:
            return ServiceResult.fail("CONFLICT", "You have already rated this chat.")
        logger.info("Rating %s submitted for chat %s", rating.id, chat.id)
        return ServiceResult.ok(rating)

    def _validate_responses(
        self, questionnaire: dict[str, Any], responses: dict[str, str]
    ) -> ServiceResult | None:
        valid_keys = {q.get("key") for q in questionnaire.get("questions", [])}
        for key, value in responses.items():
            if key not in valid_keys:
                return ServiceResult.fail(
                    "VALIDATION_ERROR", f"Unknown question: {key}."
                )
            if value not in _VALID_RESPONSES:
                return ServiceResult.fail(
                    "VALIDATION_ERROR", f"Invalid response value: {value}."
                )
        return None
