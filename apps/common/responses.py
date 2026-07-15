"""
Standardized API response envelopes.

Every REST response follows the frozen contract in API_DESIGN.md:

    success: {"success": true,  "data": {...}, "message": null}
    error:   {"success": false, "error": {"code": "...", "message": "..."}}

These helpers keep hand-built responses consistent. Step 6 adds the global
renderer and exception handler that apply the same envelope automatically; until
then, views that respond directly (e.g. the session bootstrap) use these.
"""

from __future__ import annotations

from typing import Any

from rest_framework.response import Response


def envelope_success(
    data: Any = None,
    message: str | None = None,
    status_code: int = 200,
) -> Response:
    """Wrap a successful payload in the standard success envelope."""
    return Response(
        {"success": True, "data": data, "message": message},
        status=status_code,
    )


def envelope_error(
    code: str,
    message: str,
    status_code: int,
) -> Response:
    """Wrap an error in the standard error envelope.

    ``code`` is the stable, machine-readable contract the client keys behavior
    on; ``message`` is human-readable and must not be parsed by clients.
    """
    return Response(
        {"success": False, "error": {"code": code, "message": message}},
        status=status_code,
    )
