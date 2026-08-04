"""The WebSocket origin validator is strict in prod and relaxed in dev."""

from __future__ import annotations

from channels.security.websocket import OriginValidator
from django.test import SimpleTestCase

from config.asgi import build_websocket_router


class WebSocketOriginRouterTests(SimpleTestCase):
    def test_dev_skips_origin_validator(self) -> None:
        # In DEBUG the app is returned unwrapped so native (no-Origin) sockets
        # from the emulator are not rejected at the origin layer.
        app = object()
        self.assertIs(build_websocket_router(app, debug=True), app)

    def test_prod_wraps_with_origin_validator(self) -> None:
        # AllowedHostsOriginValidator is a factory returning an OriginValidator.
        app = object()
        wrapped = build_websocket_router(app, debug=False)
        self.assertIsNot(wrapped, app)
        self.assertIsInstance(wrapped, OriginValidator)
