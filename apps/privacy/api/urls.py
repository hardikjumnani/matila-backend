"""Client-facing privacy API routes."""

from __future__ import annotations

from django.urls import path

from apps.privacy.api.views import ViolationReportView

app_name = "privacy"

urlpatterns = [
    path("privacy/violations", ViolationReportView.as_view(), name="violation-report"),
]
