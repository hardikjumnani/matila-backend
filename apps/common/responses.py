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

from rest_framework import status as http
from rest_framework.response import Response

from apps.common.results import ServiceResult

# Maps a stable business error code to its HTTP status. Codes mirror the
# "Common Error Codes" table in API_DESIGN.md plus the WebSocket/domain codes.
ERROR_STATUS_MAP: dict[str, int] = {
    "UNAUTHORIZED": http.HTTP_401_UNAUTHORIZED,
    "FORBIDDEN": http.HTTP_403_FORBIDDEN,
    "ONBOARDING_INCOMPLETE": http.HTTP_403_FORBIDDEN,
    "VERIFICATION_REQUIRED": http.HTTP_403_FORBIDDEN,
    "COLLEGE_NOT_SUPPORTED": http.HTTP_403_FORBIDDEN,
    "COLLEGE_NOT_LAUNCHED": http.HTTP_403_FORBIDDEN,
    "ACCOUNT_SUSPENDED": http.HTTP_403_FORBIDDEN,
    "ACCOUNT_BANNED": http.HTTP_403_FORBIDDEN,
    "RESOURCE_NOT_FOUND": http.HTTP_404_NOT_FOUND,
    "VALIDATION_ERROR": http.HTTP_400_BAD_REQUEST,
    "CONFLICT": http.HTTP_409_CONFLICT,
    "CHAT_READ_ONLY": http.HTTP_409_CONFLICT,
    # Payment/coin 409 variants — let the client route without a re-GET:
    # insufficient coins -> open store; already paid -> waiting; no active round -> refresh.
    "INSUFFICIENT_COINS": http.HTTP_409_CONFLICT,
    "ALREADY_PAID": http.HTTP_409_CONFLICT,
    "NO_ACTIVE_PAYMENT": http.HTTP_409_CONFLICT,
    "MESSAGE_TOO_LONG": http.HTTP_400_BAD_REQUEST,
    "INVALID_REPLY_TARGET": http.HTTP_400_BAD_REQUEST,
    "MEDIA_NOT_AVAILABLE": http.HTTP_410_GONE,
    "METHOD_NOT_ALLOWED": http.HTTP_405_METHOD_NOT_ALLOWED,
    "RATE_LIMITED": http.HTTP_429_TOO_MANY_REQUESTS,
    "INTERNAL_SERVER_ERROR": http.HTTP_500_INTERNAL_SERVER_ERROR,
}


def http_status_for_code(code: str | None) -> int:
    """Resolve the HTTP status for a business error code (400 by default)."""
    return ERROR_STATUS_MAP.get(code or "", http.HTTP_400_BAD_REQUEST)


def service_failure_response(result: ServiceResult) -> Response:
    """Turn a failed ServiceResult into the standard error envelope response."""
    return envelope_error(
        result.error_code or "INTERNAL_SERVER_ERROR",
        result.error_message or "An unexpected error occurred.",
        http_status_for_code(result.error_code),
    )


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
