"""URL routes for the admin API (all under /admin/)."""

from __future__ import annotations

from django.urls import path

from apps.admin_panel.api.college_views import (
    AdminCollegeDetailView,
    AdminCollegeListView,
)
from apps.admin_panel.api.management_views import (
    AdminAppConfigListView,
    AdminAppConfigUpdateView,
    AdminAuditLogListView,
    AdminDashboardStatsView,
    AdminFeatureFlagListView,
    AdminFeatureFlagUpdateView,
    AdminUserActivateView,
    AdminUserBanView,
    AdminUserDetailView,
    AdminUserEraseView,
    AdminUserListView,
    AdminUserSuspendView,
)
from apps.admin_panel.api.report_views import (
    AdminReportDetailView,
    AdminReportDismissView,
    AdminReportListView,
    AdminReportResolveView,
)
from apps.admin_panel.api.safety_views import (
    AdminLeakEventListView,
    AdminOffenderListView,
    AdminProfanityEventListView,
    AdminResetStrikesView,
    AdminSafetyStatsView,
    AdminUserSafetyDetailView,
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
    # User management
    path("admin/users", AdminUserListView.as_view(), name="user-list"),
    path(
        "admin/users/<uuid:user_id>",
        AdminUserDetailView.as_view(),
        name="user-detail",
    ),
    path(
        "admin/users/<uuid:user_id>/suspend",
        AdminUserSuspendView.as_view(),
        name="user-suspend",
    ),
    path(
        "admin/users/<uuid:user_id>/activate",
        AdminUserActivateView.as_view(),
        name="user-activate",
    ),
    path(
        "admin/users/<uuid:user_id>/ban",
        AdminUserBanView.as_view(),
        name="user-ban",
    ),
    path(
        "admin/users/<uuid:user_id>/erase",
        AdminUserEraseView.as_view(),
        name="user-erase",
    ),
    # Feature flags
    path(
        "admin/feature-flags",
        AdminFeatureFlagListView.as_view(),
        name="feature-flag-list",
    ),
    path(
        "admin/feature-flags/<str:key>",
        AdminFeatureFlagUpdateView.as_view(),
        name="feature-flag-update",
    ),
    # App config
    path(
        "admin/app-config",
        AdminAppConfigListView.as_view(),
        name="app-config-list",
    ),
    path(
        "admin/app-config/<str:key>",
        AdminAppConfigUpdateView.as_view(),
        name="app-config-update",
    ),
    # College management
    path("admin/colleges", AdminCollegeListView.as_view(), name="college-list"),
    path(
        "admin/colleges/<uuid:college_id>",
        AdminCollegeDetailView.as_view(),
        name="college-detail",
    ),
    # Audit logs & dashboard
    path("admin/audit-logs", AdminAuditLogListView.as_view(), name="audit-log-list"),
    path(
        "admin/dashboard/stats",
        AdminDashboardStatsView.as_view(),
        name="dashboard-stats",
    ),
    # Trust & safety (Veil / Muffle review)
    path(
        "admin/safety/leak-events",
        AdminLeakEventListView.as_view(),
        name="safety-leak-events",
    ),
    path(
        "admin/safety/profanity-events",
        AdminProfanityEventListView.as_view(),
        name="safety-profanity-events",
    ),
    path(
        "admin/safety/offenders",
        AdminOffenderListView.as_view(),
        name="safety-offenders",
    ),
    path("admin/safety/stats", AdminSafetyStatsView.as_view(), name="safety-stats"),
    path(
        "admin/safety/users/<uuid:user_id>",
        AdminUserSafetyDetailView.as_view(),
        name="safety-user-detail",
    ),
    path(
        "admin/safety/users/<uuid:user_id>/reset-strikes",
        AdminResetStrikesView.as_view(),
        name="safety-reset-strikes",
    ),
]
