"""
Reveal API views.

Chat-scoped and participant-guarded. Views delegate to RevealService, which
owns eligibility, independent intents, mutual detection, and completion.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chats.permissions import IsChatParticipant
from apps.common.responses import service_failure_response
from apps.reveal.services.reveal_service import RevealService


class _RevealBaseView(APIView):
    permission_classes = [IsAuthenticated, IsChatParticipant]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = RevealService()


class RevealIntentView(_RevealBaseView):
    """POST /chats/{id}/reveal-intent — express independent reveal intent."""

    @extend_schema(
        request=None, responses=OpenApiResponse(description="Reveal intent recorded.")
    )
    def post(self, request: Request, chat_id: str) -> Response:
        result = self.service.submit_intent(chat_id=chat_id, user=request.user)
        if result.failed:
            return service_failure_response(result)
        return Response(result.data)


class RevealStatusView(_RevealBaseView):
    """GET /chats/{id}/reveal-status — this user's reveal status for the chat."""

    @extend_schema(responses=OpenApiResponse(description="Reveal status."))
    def get(self, request: Request, chat_id: str) -> Response:
        result = self.service.get_status(chat_id=chat_id, user=request.user)
        if result.failed:
            return service_failure_response(result)
        return Response(result.data)


class RevealEligibilityView(_RevealBaseView):
    """GET /chats/{id}/reveal-eligibility — whether reveal is available."""

    @extend_schema(responses=OpenApiResponse(description="Reveal eligibility."))
    def get(self, request: Request, chat_id: str) -> Response:
        result = self.service.get_eligibility(chat_id=chat_id)
        if result.failed:
            return service_failure_response(result)
        return Response(result.data)
