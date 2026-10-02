"""
Root URL configuration.

All application endpoints are versioned under ``/api/v1/`` and are wired in
Step 6 (REST API Implementation). Step 1 exposes only the Django admin site, the
OpenAPI schema/documentation, and a health probe.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.common.views import health_check, readiness_check

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("health/ready", readiness_check, name="readiness-check"),
    path("admin/", admin.site.urls),
    # API schema & interactive documentation.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    # Versioned API surface (grows per module through Step 6).
    path("api/v1/", include("config.api_urls")),
]

# Dev-only: local admin panel UI (reviews verifications against the admin API).
if settings.DEBUG:
    from apps.admin_panel.ui_views import admin_panel_ui

    urlpatterns += [path("admin-panel/", admin_panel_ui, name="admin-panel-ui")]
