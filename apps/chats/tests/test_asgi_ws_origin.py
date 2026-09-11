"""The WebSocket origin validator: relaxed in dev, native-friendly + strict in prod."""

from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.security.websocket import OriginValidator
from django.test import SimpleTestCase

from apps.common.ws_origin import MobileFriendlyOriginValidator
from config.asgi import build_websocket_router


class _Sentinel:
    """Records whether the wrapped ASGI app was actually reached."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send) -> None:
        self.called = True


async def _receive():
    return {"type": "websocket.connect"}


def _make_send(events):
    async def send(event):
        events.append(event)

    return send


class WebSocketOriginRouterTests(SimpleTestCase):
    def test_dev_skips_origin_validator(self) -> None:
        # In DEBUG the app is returned unwrapped so native (no-Origin) sockets
        # from the emulator are not rejected at the origin layer.
        app = object()
        self.assertIs(build_websocket_router(app, debug=True), app)

    def test_prod_wraps_with_mobile_friendly_validator(self) -> None:
        app = object()
        wrapped = build_websocket_router(app, debug=False)
        self.assertIsNot(wrapped, app)
        self.assertIsInstance(wrapped, MobileFriendlyOriginValidator)
        # Browser (Origin present) requests still go through Channels' strict check.
        # (AllowedHostsOriginValidator is a factory that returns an OriginValidator.)
        self.assertIsInstance(wrapped._strict, OriginValidator)

    def test_no_origin_native_socket_reaches_the_app(self) -> None:
        # No Origin header -> pass straight through to the app (the token gate).
        inner = _Sentinel()
        validator = MobileFriendlyOriginValidator(inner)
        async_to_sync(validator)(
            {"type": "websocket", "headers": []}, _receive, _make_send([])
        )
        self.assertTrue(inner.called)

    def test_present_origin_routes_to_strict_validator(self) -> None:
        # Origin present (a browser) -> delegated to the strict ALLOWED_HOSTS
        # validator, never straight to the app. (A stubbed strict path keeps this
        # off Channels' deny consumer, which would loop on our fake receive.)
        inner = _Sentinel()
        validator = MobileFriendlyOriginValidator(inner)
        strict = _Sentinel()
        validator._strict = strict
        async_to_sync(validator)(
            {"type": "websocket", "headers": [(b"origin", b"https://evil.example")]},
            _receive,
            _make_send([]),
        )
        self.assertTrue(strict.called)
        self.assertFalse(inner.called)
