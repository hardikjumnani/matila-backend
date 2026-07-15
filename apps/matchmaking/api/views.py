"""
Matchmaking API views.

Require a verified, onboarded user (the service re-checks eligibility as
defense in depth). Views delegate to MatchmakingService and shape responses.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.responses import service_failure_response
from apps.matchmaking.services.matchmaking_service import MatchmakingService
from apps.users.permissions import IsOnboardingCompleted, IsVerifiedUser


class _MatchmakingBaseView(APIView):
    permission_classes = [IsAuthenticated, IsOnboardingCompleted, IsVerifiedUser]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = MatchmakingService()


class MatchmakingJoinView(_MatchmakingBaseView):
    """POST /matchmaking/join — join the queue and attempt an immediate match."""

    @extend_schema(
        request=None, responses=OpenApiResponse(description="See endpoint description.")
    )
    def post(self, request: Request) -> Response:
        result = self.service.join(request.user)
        if result.failed:
            return service_failure_response(result)
        join = result.data
        return Response(
            {
                "matched": join.matched,
                "chat_id": str(join.chat.id) if join.chat else None,
                "queue_entry_id": (
                    str(join.queue_entry.id) if join.queue_entry else None
                ),
            }
        )


class MatchmakingStatusView(_MatchmakingBaseView):
    """GET /matchmaking/status — current matchmaking state."""

    @extend_schema(responses=OpenApiResponse(description="See endpoint description."))
    def get(self, request: Request) -> Response:
        return Response(self.service.get_status(request.user))


class MatchmakingLeaveView(_MatchmakingBaseView):
    """POST /matchmaking/leave — cancel the active queue entry."""

    @extend_schema(
        request=None, responses=OpenApiResponse(description="See endpoint description.")
    )
    def post(self, request: Request) -> Response:
        result = self.service.leave(request.user)
        if result.failed:
            return service_failure_response(result)
        return Response({"left": True})


class MatchmakingHeartbeatView(_MatchmakingBaseView):
    """POST /matchmaking/heartbeat — maintain queue presence."""

    @extend_schema(
        request=None, responses=OpenApiResponse(description="See endpoint description.")
    )
    def post(self, request: Request) -> Response:
        result = self.service.heartbeat(request.user)
        if result.failed:
            return service_failure_response(result)
        return Response({"ok": True})


class MatchmakingActiveRangeView(_MatchmakingBaseView):
    """GET /matchmaking/active-range — approximate active-user range."""

    @extend_schema(responses=OpenApiResponse(description="See endpoint description."))
    def get(self, request: Request) -> Response:
        return Response(self.service.get_active_user_range())
