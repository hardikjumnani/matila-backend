"""
WebSocket origin policy for a token-authenticated native client.

``AllowedHostsOriginValidator`` rejects any handshake whose ``Origin`` header is
absent or not in ``ALLOWED_HOSTS``. That defends browsers against Cross-Site
WebSocket Hijacking (CSWSH) — an attack that requires *ambient* credentials
(cookies the browser auto-sends) and a browser (which always sends ``Origin``).

Matila's sockets authenticate with a **Firebase ID token in the query string**,
not cookies, so CSWSH cannot succeed here: a hostile cross-site page can't obtain
the token, and the Firebase middleware rejects any socket without a valid one. The
only casualty of strict origin validation is the legitimate **native app**, which
sends no ``Origin`` at all and gets a 403 before auth even runs.

This validator therefore: passes **no-Origin** (native) sockets straight through to
the token middleware — the real gate — while still enforcing ``ALLOWED_HOSTS``
strictly whenever an ``Origin`` *is* present (keeping the browser CSWSH defence).
"""

from __future__ import annotations

from channels.security.websocket import AllowedHostsOriginValidator


class MobileFriendlyOriginValidator:
    """Allow credential-less native sockets; keep browser origins strict."""

    def __init__(self, application) -> None:
        self.application = application
        # Reuse Channels' own ALLOWED_HOSTS logic for the browser (Origin present) path.
        self._strict = AllowedHostsOriginValidator(application)

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        if b"origin" not in headers:
            # No Origin header -> non-browser (the app). Not subject to CSWSH; the
            # Firebase token middleware still authenticates the connection.
            return await self.application(scope, receive, send)
        # Origin present -> a browser. Enforce ALLOWED_HOSTS.
        return await self._strict(scope, receive, send)
