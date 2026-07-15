"""URL routes for the ratings API."""

from __future__ import annotations

from django.urls import path

from apps.ratings.api.views import (
    RatingQuestionnaireView,
    RatingStatusView,
    RatingSubmitView,
)

app_name = "ratings"

urlpatterns = [
    path(
        "chats/<uuid:chat_id>/rating-questionnaire",
        RatingQuestionnaireView.as_view(),
        name="questionnaire",
    ),
    path("chats/<uuid:chat_id>/ratings", RatingSubmitView.as_view(), name="submit"),
    path(
        "chats/<uuid:chat_id>/rating-status",
        RatingStatusView.as_view(),
        name="status",
    ),
]
