"""
Channels middleware that authenticates WebSocket connections with Firebase.

Per WEBSOCKET_PROTOCOL_DESIGN.md the token is supplied in the query string:

    wss://host/ws/chat/{chat_id}/?token={firebase_id_token}

The middleware verifies the token, resolves the active application user, and
populates ``scope["user"]`` (an authenticated ``User`` or ``AnonymousUser``) and
``scope["firebase_claims"]``. It never rejects the connection itself — the
consumer (Step 7) inspects ``scope["user"]`` and closes with the appropriate
rejection code (4001, etc.). Verification and DB access run off the event loop.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from channels.db import close_old_connections, database_sync_to_async
from django.contrib.auth.models import AnonymousUser

from apps.common.firebase import verify_id_token
from apps.users.enums import AccountStatus
from apps.users.services.auth_service import AuthService

logger = logging.getLogger(__name__)


def _token_from_scope(scope: dict) -> str | None:
    """Extract the ``token`` query-string parameter from the connection scope."""
    query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
    tokens = parse_qs(query_string).get("token")
    return tokens[0] if tokens else None


@database_sync_to_async
def _resolve_active_user(firebase_uid: str):
    """Return the active user for a UID, or ``None``. Runs in a worker thread."""
    user = AuthService().get_user_by_firebase_uid(firebase_uid)
    if user is None or user.account_status != AccountStatus.ACTIVE:
        return None
    return user


class FirebaseAuthMiddleware:
    """Populate ``scope['user']`` from a Firebase ID token in the query string."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        # Ensure no stale DB connection is reused across connections.
        close_old_connections()

        scope = dict(scope)
        user = AnonymousUser()
        claims = None

        token = _token_from_scope(scope)
        if token:
            try:
                claims = await database_sync_to_async(verify_id_token)(token)
                resolved = await _resolve_active_user(claims.get("uid", ""))
                if resolved is not None:
                    user = resolved
            except Exception as exc:  # noqa: BLE001 — never fail the handshake here.
                logger.debug("WebSocket authentication failed: %s", exc)

        scope["user"] = user
        scope["firebase_claims"] = claims
        return await self.app(scope, receive, send)
