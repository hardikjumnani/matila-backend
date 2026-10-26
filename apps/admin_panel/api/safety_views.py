"""
Admin Trust & Safety API: read views over the Veil / Muffle privacy engines plus
a strike reset. Powers the admin panel's T&S screen. All aggregation lives in
``TrustSafetyService``; these views stay thin and serialise.
"""

from __future__ import annotations

from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.admin_panel.api.base import AdminAPIView
from apps.admin_panel.api.serializers import (
    AdminLeakEventSerializer,
    AdminMessageSerializer,
    AdminProfanityEventSerializer,
    AdminSuspicionEventSerializer,
    AdminUserSerializer,
    ReviewActionSerializer,
    SuspicionReviewSerializer,
)
from apps.admin_panel.permissions import IsAdminUser
from apps.common.responses import envelope_error, service_failure_response
from apps.privacy.services.trust_safety_service import TrustSafetyService
from apps.users.models import User


def _int(params, key, default):
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


class AdminLeakEventListView(ListAPIView):
    """GET /admin/safety/leak-events: filtered Veil leak events (cursor-paginated)."""

    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AdminLeakEventSerializer

    def get_queryset(self):
        p = self.request.query_params
        return TrustSafetyService().leak_events(
            user_id=p.get("user_id"),
            chat_id=p.get("chat_id"),
            category=p.get("category"),
            severity=p.get("severity"),
            action=p.get("action"),
            mode=p.get("mode"),
            source=p.get("source"),
        )


class AdminSuspicionEventListView(ListAPIView):
    """GET /admin/safety/suspicion-events: second-hand Veil soft signals."""

    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AdminSuspicionEventSerializer

    def get_queryset(self):
        p = self.request.query_params
        return TrustSafetyService().suspicion_events(
            user_id=p.get("user_id"),
            chat_id=p.get("chat_id"),
            signal=p.get("signal"),
            min_score=_int(p, "min_score", 0) or None,
        )


class AdminProfanityEventListView(ListAPIView):
    """GET /admin/safety/profanity-events: filtered Muffle events (cursor-paginated)."""

    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AdminProfanityEventSerializer

    def get_queryset(self):
        p = self.request.query_params
        return TrustSafetyService().profanity_events(
            user_id=p.get("user_id"),
            chat_id=p.get("chat_id"),
            tier=p.get("tier"),
            mode=p.get("mode"),
        )


class AdminOffenderListView(AdminAPIView):
    """GET /admin/safety/offenders: users with strikes, most severe first (top-N)."""

    def get(self, request: Request) -> Response:
        p = request.query_params
        return Response(
            TrustSafetyService().offenders(
                min_count=_int(p, "min_count", 1),
                limit=min(_int(p, "limit", 50), 200),
                offset=max(_int(p, "offset", 0), 0),
            )
        )


class AdminOffenderSuspicionListView(AdminAPIView):
    """GET /admin/safety/suspicion-offenders: users by suspicion score (top-N)."""

    def get(self, request: Request) -> Response:
        p = request.query_params
        return Response(
            TrustSafetyService().suspicion_offenders(
                min_score=_int(p, "min_score", 1),
                review_status=p.get("review_status"),
                limit=min(_int(p, "limit", 50), 200),
                offset=max(_int(p, "offset", 0), 0),
            )
        )


class AdminUserSafetyDetailView(AdminAPIView):
    """GET /admin/safety/users/{user_id}: one user's full T&S profile."""

    def get(self, request: Request, user_id: str) -> Response:
        data = TrustSafetyService().user_safety(user_id)
        if data is None:
            return envelope_error("RESOURCE_NOT_FOUND", "User not found.", 404)
        return Response(
            {
                "user": AdminUserSerializer(data["user"]).data,
                "strikes": data["strikes"],
                "suspicion": data["suspicion"],
                "counts": data["counts"],
                "recent_leak_events": AdminLeakEventSerializer(
                    data["recent_leaks"], many=True
                ).data,
                "recent_profanity_events": AdminProfanityEventSerializer(
                    data["recent_profanity"], many=True
                ).data,
                "recent_suspicion_events": AdminSuspicionEventSerializer(
                    data["recent_suspicions"], many=True
                ).data,
            }
        )


class AdminSuspicionReviewView(AdminAPIView):
    """POST /admin/safety/users/{user_id}/suspicion/review: admin assessment.

    Advisory only (sets review status + notes). Account actions stay in the
    suspend/ban/report-resolve flows."""

    def post(self, request: Request, user_id: str) -> Response:
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return envelope_error("RESOURCE_NOT_FOUND", "User not found.", 404)
        serializer = SuspicionReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = TrustSafetyService().review_suspicion(
            user=user,
            status=serializer.validated_data["status"],
            admin_id=str(request.user.id),
            notes=serializer.validated_data.get("notes", ""),
        )
        if result.failed:
            return service_failure_response(result)
        return Response(result.data)


class AdminSuspicionResetView(AdminAPIView):
    """POST /admin/safety/users/{user_id}/suspicion/reset: clear a user's
    accumulated suspicion (score + priority + tier) and mark it CLEARED. Lets an
    admin wipe a false accumulation in one click. Advisory only; audited."""

    def post(self, request: Request, user_id: str) -> Response:
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return envelope_error("RESOURCE_NOT_FOUND", "User not found.", 404)
        result = TrustSafetyService().reset_suspicion_score(
            user=user,
            admin_id=str(request.user.id),
            notes=str(request.data.get("notes", "") or ""),
        )
        if result.failed:
            return service_failure_response(result)
        return Response(result.data)


class AdminSafetyStatsView(AdminAPIView):
    """GET /admin/safety/stats: headline T&S counts for the dashboard."""

    def get(self, request: Request) -> Response:
        return Response(TrustSafetyService().stats())


class AdminChatMessagesView(AdminAPIView):
    """GET /admin/chats/{chat_id}/messages: full chat transcript as evidence.

    Lets a safety feed (leak/profanity/suspicion events, which carry a chat_id)
    open the conversation. Mirrors the report-detail transcript; admin-only."""

    def get(self, request: Request, chat_id: str) -> Response:
        from apps.chats.models import Chat, ChatParticipant
        from apps.messaging.models import Message

        chat = Chat.objects.filter(id=chat_id).first()
        if chat is None:
            return envelope_error("RESOURCE_NOT_FOUND", "Chat not found.", 404)
        messages = (
            Message.objects.filter(chat_id=chat_id)
            .prefetch_related("reactions")
            .order_by("created_at")
        )
        participant_ids = [
            str(uid)
            for uid in ChatParticipant.objects.filter(chat_id=chat_id).values_list(
                "user_id", flat=True
            )
        ]
        return Response(
            {
                "chat_id": str(chat.id),
                "status": chat.status,
                "participant_ids": participant_ids,
                "messages": AdminMessageSerializer(messages, many=True).data,
            }
        )


class AdminResetStrikesView(AdminAPIView):
    """POST /admin/safety/users/{user_id}/reset-strikes: clemency / false-positive."""

    def post(self, request: Request, user_id: str) -> Response:
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return envelope_error("RESOURCE_NOT_FOUND", "User not found.", 404)
        serializer = ReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = TrustSafetyService().reset_strikes(
            user=user,
            admin_id=str(request.user.id),
            notes=serializer.validated_data.get("notes", ""),
        )
        if result.failed:
            return service_failure_response(result)
        return Response(result.data)
