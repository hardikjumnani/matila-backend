"""
Chats API views.

Chat-scoped endpoints require the caller to be a participant. Views delegate all
state transitions to ChatService and only shape responses.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chats.api.serializers import ChatReadRequestSerializer, ChatSerializer
from apps.chats.models import Chat, ChatParticipant
from apps.chats.permissions import IsChatParticipant
from apps.chats.services.chat_service import ChatService
from apps.common.responses import envelope_error, service_failure_response
from apps.configuration.services.configuration_service import ConfigurationService


def _chat_with_participants(chat_id: str) -> Chat | None:
    return (
        Chat.objects.filter(id=chat_id).prefetch_related("participants__user").first()
    )


class ChatListView(ListAPIView):
    """GET /chats — the current user's (non-hidden) chats, newest first."""

    serializer_class = ChatSerializer

    def get_queryset(self):
        chat_ids = ChatParticipant.objects.filter(
            user=self.request.user, is_chat_hidden=False
        ).values("chat_id")
        return Chat.objects.filter(id__in=chat_ids).prefetch_related(
            "participants__user"
        )


class ChatDetailView(APIView):
    """GET /chats/{id} — chat details for a participant."""

    permission_classes = [IsAuthenticated, IsChatParticipant]

    @extend_schema(responses=ChatSerializer)
    def get(self, request: Request, chat_id: str) -> Response:
        chat = _chat_with_participants(chat_id)
        if chat is None:
            return envelope_error("RESOURCE_NOT_FOUND", "Chat not found.", 404)
        return Response(ChatSerializer(chat, context={"request": request}).data)


class ChatLeaveView(APIView):
    """POST /chats/{id}/leave — leave (and end) the chat."""

    permission_classes = [IsAuthenticated, IsChatParticipant]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = ChatService()

    @extend_schema(request=None, responses=ChatSerializer)
    def post(self, request: Request, chat_id: str) -> Response:
        result = self.service.leave_chat(user=request.user, chat_id=chat_id)
        if result.failed:
            return service_failure_response(result)
        chat = _chat_with_participants(chat_id)
        return Response(ChatSerializer(chat, context={"request": request}).data)


class ChatHideView(APIView):
    """POST /chats/{id}/hide — hide the chat from the user's list."""

    permission_classes = [IsAuthenticated, IsChatParticipant]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = ChatService()

    @extend_schema(request=None, responses=OpenApiResponse(description="Chat hidden."))
    def post(self, request: Request, chat_id: str) -> Response:
        result = self.service.hide_chat(user=request.user, chat_id=chat_id)
        if result.failed:
            return service_failure_response(result)
        return Response({"hidden": True})


class ChatExpiryView(APIView):
    """GET /chats/{id}/expiry — remaining time in the current phase."""

    permission_classes = [IsAuthenticated, IsChatParticipant]

    @extend_schema(responses=OpenApiResponse(description="Chat expiry information."))
    def get(self, request: Request, chat_id: str) -> Response:
        chat = Chat.objects.filter(id=chat_id).first()
        if chat is None:
            return envelope_error("RESOURCE_NOT_FOUND", "Chat not found.", 404)
        from django.utils import timezone

        seconds_remaining = None
        if chat.current_phase_ends_at is not None:
            delta = (chat.current_phase_ends_at - timezone.now()).total_seconds()
            seconds_remaining = max(0, int(delta))
        return Response(
            {
                "status": chat.status,
                "current_phase": chat.current_phase,
                "expires_at": chat.current_phase_ends_at,
                "seconds_remaining": seconds_remaining,
                "warning_minutes": ConfigurationService().get_chat_expiry_warning_minutes(),
            }
        )


class ChatReadView(APIView):
    """POST /chats/{id}/read — advance the read pointer."""

    permission_classes = [IsAuthenticated, IsChatParticipant]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = ChatService()

    @extend_schema(
        request=ChatReadRequestSerializer,
        responses=OpenApiResponse(description="Read pointer updated."),
    )
    def post(self, request: Request, chat_id: str) -> Response:
        serializer = ChatReadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = self.service.mark_read(
            user=request.user,
            chat_id=chat_id,
            last_read_message_id=str(serializer.validated_data["last_read_message_id"]),
        )
        if result.failed:
            return service_failure_response(result)
        return Response(
            {
                "ok": True,
                "last_read_message_id": str(result.data.last_read_message_id),
            }
        )
