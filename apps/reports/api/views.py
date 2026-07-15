"""Reports API views."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.responses import envelope_error, service_failure_response
from apps.reports.api.serializers import (
    CreateReportRequestSerializer,
    ReportSerializer,
)
from apps.reports.services.report_service import ReportService


class ReportsView(ListAPIView):
    """GET /reports (own reports) and POST /reports (submit)."""

    permission_classes = [IsAuthenticated]
    serializer_class = ReportSerializer

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = ReportService()

    def get_queryset(self):
        return self.service.get_reports_by(self.request.user)

    @extend_schema(request=CreateReportRequestSerializer, responses=ReportSerializer)
    def post(self, request: Request) -> Response:
        serializer = CreateReportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.submit_report(
            reporter=request.user,
            chat_id=str(data["chat_id"]),
            category=data["category"],
            description=data["description"],
            reported_message_id=(
                str(data["reported_message_id"])
                if data.get("reported_message_id")
                else None
            ),
        )
        if result.failed:
            return service_failure_response(result)
        return Response(ReportSerializer(result.data).data, status=201)


class ReportDetailView(APIView):
    """GET /reports/{id} — the caller's own report."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = ReportService()

    @extend_schema(responses=ReportSerializer)
    def get(self, request: Request, report_id: str) -> Response:
        report = self.service.get_report_for_reporter(
            report_id=report_id, user=request.user
        )
        if report is None:
            return envelope_error("RESOURCE_NOT_FOUND", "Report not found.", 404)
        return Response(ReportSerializer(report).data)
