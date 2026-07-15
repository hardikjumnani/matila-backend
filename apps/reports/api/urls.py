"""URL routes for the reports API."""

from __future__ import annotations

from django.urls import path

from apps.reports.api.views import ReportDetailView, ReportsView

app_name = "reports"

urlpatterns = [
    path("reports", ReportsView.as_view(), name="reports"),
    path("reports/<uuid:report_id>", ReportDetailView.as_view(), name="detail"),
]
