"""
WebSocket URL routing.

Chat WebSocket route per WEBSOCKET_PROTOCOL_DESIGN:
    wss://host/ws/chat/{chat_id}/?token={firebase_id_token}
"""

from __future__ import annotations

from django.urls import URLPattern, URLResolver, path

from apps.chats.consumers import ChatConsumer

websocket_urlpatterns: list[URLPattern | URLResolver] = [
    path("ws/chat/<uuid:chat_id>/", ChatConsumer.as_asgi()),
]
