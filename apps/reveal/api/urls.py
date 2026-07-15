"""URL routes for the reveal API."""

from __future__ import annotations

from django.urls import path

from apps.reveal.api.views import (
    RevealEligibilityView,
    RevealIntentView,
    RevealStatusView,
)

app_name = "reveal"

urlpatterns = [
    path(
        "chats/<uuid:chat_id>/reveal-intent",
        RevealIntentView.as_view(),
        name="intent",
    ),
    path(
        "chats/<uuid:chat_id>/reveal-status",
        RevealStatusView.as_view(),
        name="status",
    ),
    path(
        "chats/<uuid:chat_id>/reveal-eligibility",
        RevealEligibilityView.as_view(),
        name="eligibility",
    ),
]
