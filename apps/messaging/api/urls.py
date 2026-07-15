"""URL routes for the messaging API."""

from __future__ import annotations

from django.urls import path

from apps.messaging.api.views import (
    ChatImageMessageView,
    ChatMessagesView,
    MessageDeleteView,
    MessageViewedView,
)

app_name = "messaging"

urlpatterns = [
    path("chats/<uuid:chat_id>/messages", ChatMessagesView.as_view(), name="messages"),
    path(
        "chats/<uuid:chat_id>/messages/image",
        ChatImageMessageView.as_view(),
        name="messages-image",
    ),
    path(
        "messages/<uuid:message_id>/viewed",
        MessageViewedView.as_view(),
        name="message-viewed",
    ),
    path(
        "messages/<uuid:message_id>", MessageDeleteView.as_view(), name="message-delete"
    ),
]
