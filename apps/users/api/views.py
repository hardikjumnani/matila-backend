"""
Users API views.

Only the session bootstrap endpoint is implemented in Step 4. It is the single
entry point that may create a user, so it authenticates the Firebase token
directly (rather than via the default authentication class, which requires an
already-bootstrapped user) and permits otherwise-anonymous callers.
"""

from __future__ import annotations

import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.firebase import InvalidFirebaseToken, verify_id_token
from apps.common.responses import envelope_error, envelope_success
from apps.users.api.serializers import SessionResponseSerializer, UserSerializer
from apps.users.authentication import extract_bearer_token
from apps.users.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# HTTP status per business error code returned by the bootstrap flow.
_ERROR_STATUS = {
    "VALIDATION_ERROR": status.HTTP_400_BAD_REQUEST,
    "ACCOUNT_SUSPENDED": status.HTTP_403_FORBIDDEN,
    "ACCOUNT_BANNED": status.HTTP_403_FORBIDDEN,
}


class SessionView(APIView):
    """POST /auth/session — verify the Firebase token and create/fetch the user."""

    authentication_classes: list = []  # Token is verified inline (may pre-date user).
    permission_classes = [AllowAny]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._auth_service = AuthService()

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(SessionResponseSerializer),
            401: OpenApiResponse(description="Missing or invalid Firebase token."),
            403: OpenApiResponse(description="Account suspended or banned."),
        },
        description=(
            "Verify the Firebase ID token from the Authorization header, create "
            "the user on first sign-in, and return the profile plus the next "
            "navigation action."
        ),
    )
    def post(self, request: Request) -> Response:
        token = extract_bearer_token(request)
        if not token:
            return envelope_error(
                "UNAUTHORIZED",
                "Authorization bearer token is required.",
                status.HTTP_401_UNAUTHORIZED,
            )

        try:
            claims = verify_id_token(token)
        except InvalidFirebaseToken:
            return envelope_error(
                "UNAUTHORIZED",
                "Invalid or expired token.",
                status.HTTP_401_UNAUTHORIZED,
            )

        result = self._auth_service.bootstrap_session(
            firebase_uid=claims.get("uid", ""),
            email=claims.get("email", ""),
        )
        if result.failed:
            return envelope_error(
                result.error_code,
                result.error_message,
                _ERROR_STATUS.get(result.error_code, status.HTTP_400_BAD_REQUEST),
            )

        data = result.data
        return envelope_success(
            {
                "user": UserSerializer(data.user).data,
                "next_action": data.next_action.value,
                "created": data.created,
            },
            status_code=(
                status.HTTP_201_CREATED if data.created else status.HTTP_200_OK
            ),
        )
