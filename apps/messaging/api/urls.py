"""URL routes for the messaging API."""

from __future__ import annotations

from django.urls import path

from apps.messaging.api.views import (
    ChatImageMessageView,
    ChatMessagesView,
    MessageDeleteView,
    MessageViewOnceView,
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
        "messages/<uuid:message_id>/view",
        MessageViewOnceView.as_view(),
        name="message-view",
    ),
    path(
        "messages/<uuid:message_id>", MessageDeleteView.as_view(), name="message-delete"
    ),
]
