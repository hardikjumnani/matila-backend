"""
Request-ID correlation.

A single request / WebSocket connection / Celery task is traced end-to-end by a
correlation id kept in a :class:`~contextvars.ContextVar` — async-safe under
ASGI and per-task under Celery. The id is:

- set by :class:`RequestIDMiddleware` from an inbound ``X-Request-ID`` header (or
  freshly generated), and echoed back on the response,
- set per WebSocket connection by :class:`RequestIDASGIMiddleware`,
- carried across the Celery broker (see ``config.celery`` signal handlers),
- injected onto every log record by :class:`RequestIDLogFilter`,
- defaulted into ``AuditLog.request_id`` by ``AuditService``.

Sentry tagging is best-effort and a no-op until ``sentry-sdk`` is installed
(Phase E), so the correlation lights up automatically once Sentry lands.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar, Token

HEADER_NAME = "X-Request-ID"
# WSGI/ASGI request.META key for the inbound header.
_META_KEY = "HTTP_X_REQUEST_ID"
# AuditLog.request_id is max_length=100; cap well under it and constrain the
# charset so an inbound header can't inject into logs or overflow the column.
_MAX_LEN = 64
_DISALLOWED = re.compile(r"[^A-Za-z0-9._-]")

_request_id: ContextVar[str] = ContextVar("request_id", default="")


def new_request_id() -> str:
    """Return a fresh correlation id."""
    return uuid.uuid4().hex


def sanitize(raw: str | None) -> str:
    """Return a safe id: a cleaned inbound value, or a fresh one if absent/empty."""
    if not raw:
        return new_request_id()
    cleaned = _DISALLOWED.sub("", raw.strip())[:_MAX_LEN]
    return cleaned or new_request_id()


def get_request_id() -> str:
    """Return the current correlation id (``""`` if none is bound)."""
    return _request_id.get()


def set_request_id(value: str) -> Token:
    """Bind ``value`` as the current correlation id; return a reset token."""
    token = _request_id.set(value)
    _tag_sentry(value)
    return token


def reset_request_id(token: Token) -> None:
    """Restore the correlation id to its prior value (best-effort)."""
    try:
        _request_id.reset(token)
    except (ValueError, LookupError):
        _request_id.set("")


def _tag_sentry(value: str) -> None:
    """Tag the active Sentry scope with the request id. No-op until Phase E."""
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        sentry_sdk.set_tag("request_id", value)
    except Exception:  # noqa: BLE001 — telemetry must never break the request.
        pass


class RequestIDLogFilter(logging.Filter):
    """Inject the current correlation id onto every log record as ``request_id``."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class RequestIDMiddleware:
    """Django HTTP middleware: bind an ``X-Request-ID`` for the request lifetime.

    Accepts and sanitizes an inbound header (from a trusted edge or client) or
    generates one, exposes it on the response, and clears it afterwards.
    """

    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request):
        request_id = sanitize(request.META.get(_META_KEY))
        token = set_request_id(request_id)
        try:
            response = self.get_response(request)
        finally:
            reset_request_id(token)
        response[HEADER_NAME] = request_id
        return response


class RequestIDASGIMiddleware:
    """ASGI middleware: assign a fresh correlation id per WebSocket connection.

    WebSocket handshakes from the app carry no ``X-Request-ID``, so a fresh id
    per connection is the right granularity — every log line and audit row for
    that socket's lifetime shares it.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "websocket":
            return await self.app(scope, receive, send)
        token = set_request_id(new_request_id())
        try:
            return await self.app(scope, receive, send)
        finally:
            reset_request_id(token)
