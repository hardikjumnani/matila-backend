"""
ASGI entrypoint.

Routes traffic by protocol:
  - HTTP      -> the standard Django ASGI application (REST API).
  - WebSocket -> the Channels URL router (real-time chat).

Django must be fully initialized before any consumer or model is imported, so
``get_asgi_application()`` is called first and Channels imports follow.

The Firebase WebSocket authentication middleware (Step 4 / Step 7) will wrap the
WebSocket URL router at the marked insertion point. WebSocket routes themselves
are defined in ``config.routing`` and populated in Step 7.
"""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

# Initialize Django before importing anything that touches the app registry.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from apps.users.channels_auth import FirebaseAuthMiddleware  # noqa: E402
from config.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # WebSocket connections are authenticated with a Firebase token from the
        # query string; the middleware populates scope["user"]. Chat routes and
        # consumer-level connection rejection are added in Step 7.
        "websocket": AllowedHostsOriginValidator(
            FirebaseAuthMiddleware(
                URLRouter(websocket_urlpatterns),
            ),
        ),
    }
)
