"""URL routes for the reveal / decision API."""

from __future__ import annotations

from django.urls import path

from apps.reveal.api.views import (
    DecisionView,
    RevealEligibilityView,
    SafeRevealDecisionView,
)

app_name = "reveal"

urlpatterns = [
    path(
        "chats/<uuid:chat_id>/decision",
        DecisionView.as_view(),
        name="decision",
    ),
    path(
        "chats/<uuid:chat_id>/safe-reveal/decision",
        SafeRevealDecisionView.as_view(),
        name="safe-decision",
    ),
    path(
        "chats/<uuid:chat_id>/reveal-eligibility",
        RevealEligibilityView.as_view(),
        name="eligibility",
    ),
]
