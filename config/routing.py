"""
WebSocket URL routing.

Chat WebSocket routes (``/ws/chat/<chat_id>/``) and their consumer bindings are
implemented in Step 7 (WebSocket Implementation) per WEBSOCKET_PROTOCOL_DESIGN.md.
The list is defined now so the ASGI application can import a stable symbol.
"""

from __future__ import annotations

from django.urls import URLPattern, URLResolver

websocket_urlpatterns: list[URLPattern | URLResolver] = []
