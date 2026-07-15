"""URL routes for the chats API."""

from __future__ import annotations

from django.urls import path

from apps.chats.api.views import (
    ChatDetailView,
    ChatExpiryView,
    ChatHideView,
    ChatLeaveView,
    ChatListView,
    ChatReadView,
)

app_name = "chats"

urlpatterns = [
    path("chats", ChatListView.as_view(), name="list"),
    path("chats/<uuid:chat_id>", ChatDetailView.as_view(), name="detail"),
    path("chats/<uuid:chat_id>/leave", ChatLeaveView.as_view(), name="leave"),
    path("chats/<uuid:chat_id>/hide", ChatHideView.as_view(), name="hide"),
    path("chats/<uuid:chat_id>/expiry", ChatExpiryView.as_view(), name="expiry"),
    path("chats/<uuid:chat_id>/read", ChatReadView.as_view(), name="read"),
]
