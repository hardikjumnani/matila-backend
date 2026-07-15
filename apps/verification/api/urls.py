"""URL routes for the verification API."""

from __future__ import annotations

from django.urls import path

from apps.verification.api.views import (
    SubmitVerificationView,
    UploadCollegeIdView,
    UploadGestureSelfieView,
    VerificationGestureView,
    VerificationHistoryView,
    VerificationStatusView,
)

app_name = "verification"

urlpatterns = [
    path("verification/status", VerificationStatusView.as_view(), name="status"),
    path("verification/gesture", VerificationGestureView.as_view(), name="gesture"),
    path(
        "verification/upload-college-id",
        UploadCollegeIdView.as_view(),
        name="upload-college-id",
    ),
    path(
        "verification/upload-gesture-selfie",
        UploadGestureSelfieView.as_view(),
        name="upload-gesture-selfie",
    ),
    path("verification/submit", SubmitVerificationView.as_view(), name="submit"),
    path("verification/history", VerificationHistoryView.as_view(), name="history"),
]
