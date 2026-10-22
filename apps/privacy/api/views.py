"""Client-facing privacy API: the frontend reports violations it blocked.

`POST /api/v1/privacy/violations` - the app's client-side guard stops some leak
attempts before they reach us; it reports them here so the per-person violation
log is complete. Untrusted input: authenticated, rate-limited, text-capped, and
the user is always the caller.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.common.responses import envelope_error, service_failure_response
from apps.privacy.api.serializers import ViolationReportSerializer
from apps.privacy.services.violation_service import ViolationReportService


class ViolationReportThrottle(UserRateThrottle):
    """Per-user cap so a buggy/malicious client cannot flood the violation log."""

    scope = "violation_report"

    def get_rate(self) -> str:
        return "120/min"

    def get_cache_key(self, request, view):
        user = request.user
        if user is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": user.pk}


class ViolationReportView(APIView):
    """POST /privacy/violations — record a frontend-blocked violation attempt."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ViolationReportThrottle]

    @extend_schema(
        request=ViolationReportSerializer,
        responses=OpenApiResponse(description="Violation recorded."),
    )
    def post(self, request: Request) -> Response:
        serializer = ViolationReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        chat = None
        chat_id = data.get("chat_id")
        if chat_id:
            from apps.chats.services.chat_service import ChatService

            chats = ChatService()
            chat = chats.get_chat(str(chat_id))
            if chat is None or not chats.is_participant(chat, request.user):
                return envelope_error(
                    "FORBIDDEN", "You are not a participant of this chat.", 403
                )

        result = ViolationReportService().record_frontend(
            user=request.user,
            attempted_text=data["attempted_text"],
            category=data.get("category", ""),
            chat=chat,
            client_detectors=data.get("client_detectors") or [],
        )
        if result.failed:
            return service_failure_response(result)
        return Response({"recorded": True, "id": str(result.data.id)}, status=201)
