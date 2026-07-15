"""URL routes for the users/auth API."""

from __future__ import annotations

from django.urls import path

from apps.users.api.views import SessionView

app_name = "users"

urlpatterns = [
    path("auth/session", SessionView.as_view(), name="auth-session"),
]
