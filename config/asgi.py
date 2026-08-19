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
from django.conf import settings  # noqa: E402

from apps.common.request_id import RequestIDASGIMiddleware  # noqa: E402
from apps.common.ws_origin import MobileFriendlyOriginValidator  # noqa: E402
from apps.users.channels_auth import FirebaseAuthMiddleware  # noqa: E402
from config.routing import websocket_urlpatterns  # noqa: E402


def build_websocket_router(app, *, debug: bool):
    """Wrap the WebSocket app with origin validation.

    Native mobile clients send no ``Origin`` header, which the stock
    ``AllowedHostsOriginValidator`` rejects with a 403. Local development skips
    origin validation entirely (the emulator connects over ``ws://10.0.2.2:8000/``);
    production uses :class:`MobileFriendlyOriginValidator`, which passes no-Origin
    (native) sockets through to the Firebase token middleware — the real gate —
    while still enforcing ``ALLOWED_HOSTS`` for any browser (Origin present).
    """
    if debug:
        return app
    return MobileFriendlyOriginValidator(app)


# WebSocket connections are authenticated with a Firebase token from the query
# string; the middleware populates scope["user"]. RequestIDASGIMiddleware wraps
# the outside so a correlation id is bound before origin/auth checks even run.
_websocket_app = FirebaseAuthMiddleware(URLRouter(websocket_urlpatterns))

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": RequestIDASGIMiddleware(
            build_websocket_router(_websocket_app, debug=settings.DEBUG)
        ),
    }
)
