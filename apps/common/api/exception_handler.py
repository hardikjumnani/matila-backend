"""
Global DRF exception handler.

Converts every error — domain errors, authentication/permission failures,
validation errors, and not-found — into the frozen error envelope::

    {"success": false, "error": {"code": "...", "message": "..."}}

Serializer validation errors additionally carry the field-level details under
``error.details`` so clients can surface them, while still keying behavior on
the stable ``error.code``.
"""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.common.exceptions import DomainError
from apps.common.responses import http_status_for_code

# Maps DRF's built-in exception codes to our stable business codes.
_DRF_CODE_MAP = {
    "not_authenticated": "UNAUTHORIZED",
    "authentication_failed": "UNAUTHORIZED",
    "permission_denied": "FORBIDDEN",
    "not_found": "RESOURCE_NOT_FOUND",
    "parse_error": "VALIDATION_ERROR",
    "method_not_allowed": "METHOD_NOT_ALLOWED",
    "throttled": "RATE_LIMITED",
}


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """Render any handled exception as the standard error envelope."""
    # Domain errors are not DRF exceptions; map them directly.
    if isinstance(exc, DomainError):
        return Response(
            {"success": False, "error": {"code": exc.code, "message": exc.message}},
            status=http_status_for_code(exc.code),
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        # Unhandled exception: let Django's 500 handling take over.
        return None

    if isinstance(exc, DRFValidationError):
        response.data = {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "The request data is invalid.",
                "details": exc.detail,
            },
        }
        return response

    code, message = _extract_code_and_message(exc, response.data)
    response.data = {
        "success": False,
        "error": {"code": code, "message": message},
    }
    return response


def _extract_code_and_message(exc: Exception, detail: Any) -> tuple[str, str]:
    # Our FirebaseAuthentication raises AuthenticationFailed with a
    # {"code", "detail"} dict payload.
    if isinstance(detail, dict) and "code" in detail:
        return detail.get("code", "UNAUTHORIZED"), str(
            detail.get("detail") or detail.get("message") or "Request failed."
        )

    raw_code = getattr(getattr(exc, "detail", None), "code", None)
    if raw_code in _DRF_CODE_MAP:
        code = _DRF_CODE_MAP[raw_code]
    elif isinstance(raw_code, str) and raw_code.isupper():
        # A custom permission code (e.g. VERIFICATION_REQUIRED) flows through.
        code = raw_code
    else:
        code = "INTERNAL_SERVER_ERROR"

    return code, _message_from_detail(detail)


def _message_from_detail(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        if "detail" in detail:
            return str(detail["detail"])
        return "The request could not be processed."
    if isinstance(detail, list | tuple) and detail:
        return str(detail[0])
    return str(detail)
