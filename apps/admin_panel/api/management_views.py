"""
Admin management API views: users, feature flags, app config, audit logs,
dashboard. Every mutation flows through a domain service so audit logging and
cache invalidation happen automatically.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.admin_panel.api.base import AdminAPIView
from apps.admin_panel.api.serializers import (
    AdminUserSerializer,
    AppConfigSerializer,
    AuditLogSerializer,
    FeatureFlagSerializer,
    SetValueSerializer,
)
from apps.admin_panel.permissions import IsAdminUser
from apps.admin_panel.services.dashboard_service import DashboardService
from apps.audit.models import AuditLog
from apps.chats.models import ChatParticipant
from apps.chats.services.chat_service import ChatService
from apps.common.responses import envelope_error, service_failure_response
from apps.configuration.services.configuration_service import ConfigurationService
from apps.users.enums import AccountStatus
from apps.users.models import User
from apps.users.services.auth_service import AuthService

# -- User management --------------------------------------------------------


class AdminUserListView(ListAPIView):
    """GET /admin/users — search/filter users."""

    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AdminUserSerializer

    def get_queryset(self):
        from django.db.models import Q

        params = self.request.query_params
        queryset = User.objects.all().order_by("-created_at")
        search = params.get("q")
        if search:
            queryset = queryset.filter(
                Q(college_email__icontains=search) | Q(full_name__icontains=search)
            )
        if account_status := params.get("account_status"):
            queryset = queryset.filter(account_status=account_status.upper())
        if verification_status := params.get("verification_status"):
            queryset = queryset.filter(verification_status=verification_status.upper())
        return queryset


class AdminUserDetailView(AdminAPIView):
    """GET /admin/users/{id} — user profile plus a chat summary."""

    @extend_schema(responses=OpenApiResponse(description="User detail."))
    def get(self, request: Request, user_id: str) -> Response:
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return envelope_error("RESOURCE_NOT_FOUND", "User not found.", 404)
        active_chat = ChatService().get_active_chat(user)
        summary = {
            "chat_count": ChatParticipant.objects.filter(user=user).count(),
            "active_chat_id": str(active_chat.id) if active_chat else None,
        }
        return Response(
            {"user": AdminUserSerializer(user).data, "chat_summary": summary}
        )


class _AdminUserStatusView(AdminAPIView):
    """Base for suspend/activate/ban actions."""

    target_status = ""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = AuthService()

    def _apply(self, request: Request, user_id: str) -> Response:
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return envelope_error("RESOURCE_NOT_FOUND", "User not found.", 404)
        result = self.service.update_account_status(
            user=user, status=self.target_status, admin_id=str(request.user.id)
        )
        if result.failed:
            return service_failure_response(result)
        return Response(AdminUserSerializer(result.data).data)


class AdminUserSuspendView(_AdminUserStatusView):
    target_status = AccountStatus.SUSPENDED

    @extend_schema(request=None, responses=AdminUserSerializer)
    def post(self, request: Request, user_id: str) -> Response:
        return self._apply(request, user_id)


class AdminUserActivateView(_AdminUserStatusView):
    target_status = AccountStatus.ACTIVE

    @extend_schema(request=None, responses=AdminUserSerializer)
    def post(self, request: Request, user_id: str) -> Response:
        return self._apply(request, user_id)


class AdminUserBanView(_AdminUserStatusView):
    target_status = AccountStatus.BANNED

    @extend_schema(request=None, responses=AdminUserSerializer)
    def post(self, request: Request, user_id: str) -> Response:
        return self._apply(request, user_id)


# -- Feature flags & app config --------------------------------------------


class AdminFeatureFlagListView(AdminAPIView):
    """GET /admin/feature-flags — effective flags (defaults + overrides)."""

    @extend_schema(responses=OpenApiResponse(description="Effective feature flags."))
    def get(self, request: Request) -> Response:
        return Response(ConfigurationService().get_all_flags())


class AdminFeatureFlagUpdateView(AdminAPIView):
    """PUT /admin/feature-flags/{key} — set a flag (invalidates cache, audits)."""

    @extend_schema(request=SetValueSerializer, responses=FeatureFlagSerializer)
    def put(self, request: Request, key: str) -> Response:
        serializer = SetValueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        flag = ConfigurationService().set_flag(
            key=key,
            value=serializer.validated_data["value"],
            updated_by=request.user,
            admin_id=str(request.user.id),
            description=serializer.validated_data.get("description"),
        )
        return Response(FeatureFlagSerializer(flag).data)


class AdminAppConfigListView(AdminAPIView):
    """GET /admin/app-config — effective config (defaults + overrides)."""

    @extend_schema(responses=OpenApiResponse(description="Effective app config."))
    def get(self, request: Request) -> Response:
        return Response(ConfigurationService().get_all_config())


class AdminAppConfigUpdateView(AdminAPIView):
    """PUT /admin/app-config/{key} — set a config value (invalidates, audits)."""

    @extend_schema(request=SetValueSerializer, responses=AppConfigSerializer)
    def put(self, request: Request, key: str) -> Response:
        serializer = SetValueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = ConfigurationService().set_config(
            key=key,
            value=serializer.validated_data["value"],
            updated_by=request.user,
            admin_id=str(request.user.id),
            description=serializer.validated_data.get("description"),
        )
        return Response(AppConfigSerializer(entry).data)


# -- Audit logs & dashboard -------------------------------------------------


class AdminAuditLogListView(ListAPIView):
    """GET /admin/audit-logs — filterable audit trail."""

    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        params = self.request.query_params
        queryset = AuditLog.objects.all()
        for field in ("entity_type", "entity_id", "action", "actor_id", "actor_type"):
            if value := params.get(field):
                queryset = queryset.filter(**{field: value})
        return queryset


class AdminDashboardStatsView(AdminAPIView):
    """GET /admin/dashboard/stats — operational statistics."""

    @extend_schema(responses=OpenApiResponse(description="Dashboard statistics."))
    def get(self, request: Request) -> Response:
        return Response(DashboardService().get_stats())
