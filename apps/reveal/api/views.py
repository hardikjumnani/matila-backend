"""
Reveal / decision API views.

Chat-scoped and participant-guarded. Delegate to RevealService, which owns the
decision-round state machine, Safe Reveal sub-phase, and eligibility.
See docs/REVEAL_FLOW_SPEC.md.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chats.permissions import IsChatParticipant
from apps.common.responses import service_failure_response
from apps.reveal.api.serializers import (
    DecisionRequestSerializer,
    SafeDecisionRequestSerializer,
)
from apps.reveal.services.reveal_service import RevealService


class _RevealBaseView(APIView):
    permission_classes = [IsAuthenticated, IsChatParticipant]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = RevealService()


class DecisionView(_RevealBaseView):
    """GET/POST /chats/{id}/decision — read the decision state, or submit a
    choice (REVEAL / SAFE_REVEAL / EXTEND / EXIT)."""

    @extend_schema(responses=OpenApiResponse(description="Current decision state."))
    def get(self, request: Request, chat_id: str) -> Response:
        result = self.service.get_decision_state(chat_id=chat_id, user=request.user)
        if result.failed:
            return service_failure_response(result)
        return Response(result.data)

    @extend_schema(
        request=DecisionRequestSerializer,
        responses=OpenApiResponse(description="Decision recorded."),
    )
    def post(self, request: Request, chat_id: str) -> Response:
        serializer = DecisionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = self.service.submit_decision(
            chat_id=chat_id, user=request.user, choice=serializer.validated_data["choice"]
        )
        if result.failed:
            return service_failure_response(result)
        return Response(result.data)


class SafeRevealDecisionView(_RevealBaseView):
    """POST /chats/{id}/safe-reveal/decision — the reviewing user chooses
    REVEAL_YOURSELF or EXIT after seeing the other person."""

    @extend_schema(
        request=SafeDecisionRequestSerializer,
        responses=OpenApiResponse(description="Safe reveal decision recorded."),
    )
    def post(self, request: Request, chat_id: str) -> Response:
        serializer = SafeDecisionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = self.service.submit_safe_decision(
            chat_id=chat_id, user=request.user, choice=serializer.validated_data["choice"]
        )
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
