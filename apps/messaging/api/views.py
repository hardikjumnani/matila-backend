"""
Messaging API views.

Chat-scoped endpoints (``/chats/{id}/...``) require chat participation via the
permission; message-scoped endpoints (``/messages/{id}/...``) rely on the
service's own participant/sender checks. All business rules live in
MessageService.
"""

from __future__ import annotations

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chats.permissions import IsChatParticipant
from apps.common.responses import service_failure_response
from apps.messaging.api.serializers import (
    MessageSerializer,
    SendImageMessageSerializer,
    SendTextMessageSerializer,
)
from apps.messaging.models import Message
from apps.messaging.services.message_service import MessageService


class ChatMessagesView(ListAPIView):
    """GET/POST /chats/{id}/messages — list (paginated) or send a text message."""

    permission_classes = [IsAuthenticated, IsChatParticipant]
    serializer_class = MessageSerializer

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = MessageService()

    def get_queryset(self):
        # Newest-first, cursor-paginated (see StandardCursorPagination.ordering).
        return Message.objects.filter(chat_id=self.kwargs["chat_id"])

    @extend_schema(request=SendTextMessageSerializer, responses=MessageSerializer)
    def post(self, request: Request, chat_id: str) -> Response:
        serializer = SendTextMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.send_text(
            chat_id=chat_id,
            sender=request.user,
            content=data["content"],
            reply_to_message_id=(
                str(data["reply_to_message_id"])
                if data.get("reply_to_message_id")
                else None
            ),
        )
        if result.failed:
            return service_failure_response(result)
        return Response(MessageSerializer(result.data).data, status=201)


class ChatImageMessageView(APIView):
    """POST /chats/{id}/messages/image — send an image message."""

    permission_classes = [IsAuthenticated, IsChatParticipant]
    parser_classes = [MultiPartParser, FormParser]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = MessageService()

    @extend_schema(request=SendImageMessageSerializer, responses=MessageSerializer)
    def post(self, request: Request, chat_id: str) -> Response:
        serializer = SendImageMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        upload = data["file"]
        result = self.service.send_image(
            chat_id=chat_id,
            sender=request.user,
            fileobj=upload,
            filename=upload.name,
            content_type=upload.content_type,
            visibility=data["media_visibility"],
            reply_to_message_id=(
                str(data["reply_to_message_id"])
                if data.get("reply_to_message_id")
                else None
            ),
        )
        if result.failed:
            return service_failure_response(result)
        return Response(MessageSerializer(result.data).data, status=201)


class MessageViewOnceView(APIView):
    """POST /messages/{id}/view — consume a view-once image and stream its bytes.

    The image is delivered exactly once, server-mediated: the body is the raw
    image (no shareable URL is ever exposed), the AVAILABLE→VIEWED transition is
    atomic, and the blob is deleted immediately after. A second call returns
    410 MEDIA_NOT_AVAILABLE.
    """

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = MessageService()

    @extend_schema(request=None, responses=bytes)
    def post(self, request: Request, message_id: str):
        result = self.service.view_once(message_id=message_id, user=request.user)
        if result.failed:
            return service_failure_response(result)
        data, content_type = result.data
        response = HttpResponse(data, content_type=content_type)
        response["Cache-Control"] = "no-store"
        response["Content-Disposition"] = "inline"
        return response


class MessageDeleteView(APIView):
    """DELETE /messages/{id} — soft-delete the caller's own message."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = MessageService()

    @extend_schema(responses=MessageSerializer)
    def delete(self, request: Request, message_id: str) -> Response:
        result = self.service.soft_delete(message_id=message_id, user=request.user)
        if result.failed:
            return service_failure_response(result)
        return Response(MessageSerializer(result.data).data)
