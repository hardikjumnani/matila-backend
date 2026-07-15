"""URL routes for the admin API (all under /admin/)."""

from __future__ import annotations

from django.urls import path

from apps.admin_panel.api.report_views import (
    AdminReportDetailView,
    AdminReportDismissView,
    AdminReportListView,
    AdminReportResolveView,
)
from apps.admin_panel.api.verification_views import (
    AdminVerificationApproveView,
    AdminVerificationDetailView,
    AdminVerificationListView,
    AdminVerificationRejectView,
    AdminVerificationResubmissionView,
)

app_name = "admin_panel"

urlpatterns = [
    # Verification review
    path(
        "admin/verifications",
        AdminVerificationListView.as_view(),
        name="verification-list",
    ),
    path(
        "admin/verifications/<uuid:request_id>",
        AdminVerificationDetailView.as_view(),
        name="verification-detail",
    ),
    path(
        "admin/verifications/<uuid:request_id>/approve",
        AdminVerificationApproveView.as_view(),
        name="verification-approve",
    ),
    path(
        "admin/verifications/<uuid:request_id>/reject",
        AdminVerificationRejectView.as_view(),
        name="verification-reject",
    ),
    path(
        "admin/verifications/<uuid:request_id>/request-resubmission",
        AdminVerificationResubmissionView.as_view(),
        name="verification-resubmission",
    ),
    # Report moderation
    path("admin/reports", AdminReportListView.as_view(), name="report-list"),
    path(
        "admin/reports/<uuid:report_id>",
        AdminReportDetailView.as_view(),
        name="report-detail",
    ),
    path(
        "admin/reports/<uuid:report_id>/resolve",
        AdminReportResolveView.as_view(),
        name="report-resolve",
    ),
    path(
        "admin/reports/<uuid:report_id>/dismiss",
        AdminReportDismissView.as_view(),
        name="report-dismiss",
    ),
]
