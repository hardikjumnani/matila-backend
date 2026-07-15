"""URL routes for the configuration API."""

from __future__ import annotations

from django.urls import path

from apps.configuration.api.views import ConfigView

app_name = "configuration"

urlpatterns = [
    path("config", ConfigView.as_view(), name="config"),
]
