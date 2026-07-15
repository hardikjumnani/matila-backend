"""Admin verification-review API views."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.admin_panel.api.base import AdminAPIView
from apps.admin_panel.api.serializers import (
    AdminVerificationRequestSerializer,
    ReviewActionSerializer,
)
from apps.admin_panel.permissions import IsAdminUser
from apps.common.responses import envelope_error, service_failure_response
from apps.users.enums import VerificationStatus
from apps.verification.models import VerificationRequest
from apps.verification.services.verification_service import VerificationService


class AdminVerificationListView(ListAPIView):
    """GET /admin/verifications — submitted requests (default: pending)."""

    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AdminVerificationRequestSerializer

    def get_queryset(self):
        status_filter = self.request.query_params.get(
            "status", VerificationStatus.PENDING
        )
        queryset = VerificationRequest.objects.filter(
            submitted_at__isnull=False
        ).order_by("-submitted_at")
        if status_filter and status_filter.upper() != "ALL":
            queryset = queryset.filter(status=status_filter.upper())
        return queryset


class AdminVerificationDetailView(AdminAPIView):
    """GET /admin/verifications/{id}."""

    @extend_schema(responses=AdminVerificationRequestSerializer)
    def get(self, request: Request, request_id: str) -> Response:
        obj = VerificationRequest.objects.filter(id=request_id).first()
        if obj is None:
            return envelope_error(
                "RESOURCE_NOT_FOUND", "Verification request not found.", 404
            )
        return Response(AdminVerificationRequestSerializer(obj).data)


class _AdminVerificationActionView(AdminAPIView):
    """Base for approve/reject/resubmission actions."""

    action_name = ""  # set by subclasses

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = VerificationService()

    def _run(self, request: Request, request_id: str):
        serializer = ReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        method = getattr(self.service, self.action_name)
        result = method(
            request_id=request_id,
            reviewed_by=request.user,
            admin_id=str(request.user.id),
            notes=serializer.validated_data["notes"],
        )
        if result.failed:
            return service_failure_response(result)
        return Response(AdminVerificationRequestSerializer(result.data).data)


class AdminVerificationApproveView(_AdminVerificationActionView):
    """POST /admin/verifications/{id}/approve."""

    action_name = "approve"

    @extend_schema(
        request=ReviewActionSerializer, responses=AdminVerificationRequestSerializer
    )
    def post(self, request: Request, request_id: str) -> Response:
        return self._run(request, request_id)


class AdminVerificationRejectView(_AdminVerificationActionView):
    """POST /admin/verifications/{id}/reject."""

    action_name = "reject"

    @extend_schema(
        request=ReviewActionSerializer, responses=AdminVerificationRequestSerializer
    )
    def post(self, request: Request, request_id: str) -> Response:
        return self._run(request, request_id)


class AdminVerificationResubmissionView(_AdminVerificationActionView):
    """POST /admin/verifications/{id}/request-resubmission."""

    action_name = "request_resubmission"

    @extend_schema(
        request=ReviewActionSerializer, responses=AdminVerificationRequestSerializer
    )
    def post(self, request: Request, request_id: str) -> Response:
        return self._run(request, request_id)
