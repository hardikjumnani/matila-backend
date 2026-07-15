"""
Response renderer that enforces the standard success envelope.

Views return raw data (a dict, a serializer's ``.data``, or a paginated
payload); this renderer wraps successful responses as::

    {"success": true, "data": <payload>, "message": null}

Responses that are already envelopes — error responses produced by the
exception handler, or explicitly built success envelopes — are passed through
untouched, so wrapping never happens twice.
"""

from __future__ import annotations

from typing import Any

from rest_framework.renderers import JSONRenderer


class EnvelopeJSONRenderer(JSONRenderer):
    """Wrap non-envelope response bodies in the standard success envelope."""

    def render(self, data: Any, accepted_media_type=None, renderer_context=None):
        if not self._is_envelope(data):
            data = {"success": True, "data": data, "message": None}
        return super().render(data, accepted_media_type, renderer_context)

    @staticmethod
    def _is_envelope(data: Any) -> bool:
        return (
            isinstance(data, dict)
            and "success" in data
            and ("data" in data or "error" in data)
        )
