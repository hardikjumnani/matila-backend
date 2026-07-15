"""Admin report-moderation API views."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.admin_panel.api.base import AdminAPIView
from apps.admin_panel.api.serializers import (
    AdminMessageSerializer,
    AdminReportSerializer,
    DismissReportSerializer,
    ResolveReportSerializer,
)
from apps.admin_panel.permissions import IsAdminUser
from apps.common.responses import envelope_error, service_failure_response
from apps.messaging.models import Message
from apps.reports.enums import ReportStatus
from apps.reports.models import Report
from apps.reports.services.report_service import ReportService


class AdminReportListView(ListAPIView):
    """GET /admin/reports — reports (default: open)."""

    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AdminReportSerializer

    def get_queryset(self):
        status_filter = self.request.query_params.get("status", ReportStatus.OPEN)
        queryset = Report.objects.all().order_by("-created_at")
        if status_filter and status_filter.upper() != "ALL":
            queryset = queryset.filter(status=status_filter.upper())
        return queryset


class AdminReportDetailView(AdminAPIView):
    """GET /admin/reports/{id} — report plus chat evidence."""

    @extend_schema(responses=OpenApiResponse(description="Report with chat evidence."))
    def get(self, request: Request, report_id: str) -> Response:
        report = Report.objects.filter(id=report_id).first()
        if report is None:
            return envelope_error("RESOURCE_NOT_FOUND", "Report not found.", 404)
        messages = Message.objects.filter(chat_id=report.chat_id).order_by("created_at")
        return Response(
            {
                "report": AdminReportSerializer(report).data,
                "messages": AdminMessageSerializer(messages, many=True).data,
            }
        )


class AdminReportResolveView(AdminAPIView):
    """POST /admin/reports/{id}/resolve."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = ReportService()

    @extend_schema(request=ResolveReportSerializer, responses=AdminReportSerializer)
    def post(self, request: Request, report_id: str) -> Response:
        serializer = ResolveReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.resolve(
            report_id=report_id,
            admin_id=str(request.user.id),
            resolution_action=data["resolution_action"],
            admin_notes=data["admin_notes"],
            is_false_report=data["is_false_report"],
        )
        if result.failed:
            return service_failure_response(result)
        return Response(AdminReportSerializer(result.data).data)


class AdminReportDismissView(AdminAPIView):
    """POST /admin/reports/{id}/dismiss."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = ReportService()

    @extend_schema(request=DismissReportSerializer, responses=AdminReportSerializer)
    def post(self, request: Request, report_id: str) -> Response:
        serializer = DismissReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.dismiss(
            report_id=report_id,
            admin_id=str(request.user.id),
            is_false_report=data["is_false_report"],
            admin_notes=data["admin_notes"],
        )
        if result.failed:
            return service_failure_response(result)
        return Response(AdminReportSerializer(result.data).data)
