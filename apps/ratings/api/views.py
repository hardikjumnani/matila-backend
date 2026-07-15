"""Ratings API views (chat-scoped, participant-guarded)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chats.permissions import IsChatParticipant
from apps.common.responses import service_failure_response
from apps.ratings.api.serializers import (
    RatingSerializer,
    SubmitRatingRequestSerializer,
)
from apps.ratings.services.rating_service import RatingService


class _RatingBaseView(APIView):
    permission_classes = [IsAuthenticated, IsChatParticipant]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = RatingService()


class RatingQuestionnaireView(_RatingBaseView):
    """GET /chats/{id}/rating-questionnaire — the active questionnaire."""

    @extend_schema(responses=OpenApiResponse(description="Active questionnaire."))
    def get(self, request: Request, chat_id: str) -> Response:
        return Response(self.service.get_active_questionnaire())


class RatingSubmitView(_RatingBaseView):
    """POST /chats/{id}/ratings — submit a rating for an ended/expired chat."""

    @extend_schema(request=SubmitRatingRequestSerializer, responses=RatingSerializer)
    def post(self, request: Request, chat_id: str) -> Response:
        serializer = SubmitRatingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.submit_rating(
            chat_id=chat_id,
            rater=request.user,
            questionnaire_version=data["questionnaire_version"],
            responses=data["responses"],
            feedback_text=data["feedback_text"],
        )
        if result.failed:
            return service_failure_response(result)
        return Response(RatingSerializer(result.data).data, status=201)


class RatingStatusView(_RatingBaseView):
    """GET /chats/{id}/rating-status — whether the caller has rated."""

    @extend_schema(responses=OpenApiResponse(description="Rating status."))
    def get(self, request: Request, chat_id: str) -> Response:
        return Response(self.service.get_status(chat_id=chat_id, user=request.user))
