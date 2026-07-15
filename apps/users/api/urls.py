"""URL routes for the auth and users API."""

from __future__ import annotations

from django.urls import path

from apps.users.api.views import (
    CompleteOnboardingView,
    MeView,
    ProfilePhotoView,
    SessionView,
)

app_name = "users"

urlpatterns = [
    path("auth/session", SessionView.as_view(), name="auth-session"),
    path("users/me", MeView.as_view(), name="users-me"),
    path(
        "users/me/profile-photo",
        ProfilePhotoView.as_view(),
        name="users-me-profile-photo",
    ),
    path(
        "users/me/complete-onboarding",
        CompleteOnboardingView.as_view(),
        name="users-me-complete-onboarding",
    ),
]
