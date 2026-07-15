"""Notifications API views (user-scoped)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.responses import service_failure_response
from apps.notifications.api.serializers import NotificationSerializer
from apps.notifications.services.notification_service import NotificationService


class NotificationListView(ListAPIView):
    """GET /notifications — the caller's notifications (paginated, newest first)."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = NotificationService()

    def get_queryset(self):
        return self.service.for_user(self.request.user)


class UnreadCountView(APIView):
    """GET /notifications/unread-count."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = NotificationService()

    @extend_schema(responses=OpenApiResponse(description="Unread count."))
    def get(self, request: Request) -> Response:
        return Response({"unread_count": self.service.get_unread_count(request.user)})


class MarkNotificationReadView(APIView):
    """POST /notifications/{id}/read."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = NotificationService()

    @extend_schema(request=None, responses=NotificationSerializer)
    def post(self, request: Request, notification_id: str) -> Response:
        result = self.service.mark_read(
            user=request.user, notification_id=notification_id
        )
        if result.failed:
            return service_failure_response(result)
        return Response(NotificationSerializer(result.data).data)


class MarkAllNotificationsReadView(APIView):
    """POST /notifications/read-all."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = NotificationService()

    @extend_schema(
        request=None, responses=OpenApiResponse(description="All marked read.")
    )
    def post(self, request: Request) -> Response:
        count = self.service.mark_all_read(user=request.user)
        return Response({"marked_read": count})
