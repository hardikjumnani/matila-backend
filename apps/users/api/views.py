"""
Users API views.

Views are thin: authenticate, validate input, delegate to AuthService, and shape
the response. All business rules live in the service. Successful bodies are
returned raw and wrapped by the envelope renderer; service failures are mapped
to the standard error envelope by ``service_failure_response``.
"""

from __future__ import annotations

import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.firebase import InvalidFirebaseToken, verify_id_token
from apps.common.responses import envelope_error, service_failure_response
from apps.users.api.serializers import (
    ProfilePhotoUploadSerializer,
    SessionResponseSerializer,
    UserProfileUpdateSerializer,
    UserSerializer,
)
from apps.users.authentication import extract_bearer_token
from apps.users.services.auth_service import AuthService

logger = logging.getLogger(__name__)


class SessionView(APIView):
    """POST /auth/session — verify the Firebase token and create/fetch the user."""

    authentication_classes: list = []  # Token is verified inline (may pre-date user).
    permission_classes = [AllowAny]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._auth_service = AuthService()

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(SessionResponseSerializer)},
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
            return service_failure_response(result)

        data = result.data
        status_code = status.HTTP_201_CREATED if data.created else status.HTTP_200_OK
        return Response(
            {
                "user": UserSerializer(data.user).data,
                "next_action": data.next_action.value,
                "created": data.created,
            },
            status=status_code,
        )


class MeView(APIView):
    """GET/PATCH /users/me — retrieve and update the current user's profile."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._auth_service = AuthService()

    @extend_schema(responses=UserSerializer)
    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)

    @extend_schema(request=UserProfileUpdateSerializer, responses=UserSerializer)
    def patch(self, request: Request) -> Response:
        serializer = UserProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = self._auth_service.update_profile(
            request.user, **serializer.validated_data
        )
        if result.failed:
            return service_failure_response(result)
        return Response(UserSerializer(result.data).data)


class ProfilePhotoView(APIView):
    """POST /users/me/profile-photo — upload the current user's profile photo."""

    parser_classes = [MultiPartParser, FormParser]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._auth_service = AuthService()

    @extend_schema(request=ProfilePhotoUploadSerializer, responses=UserSerializer)
    def post(self, request: Request) -> Response:
        serializer = ProfilePhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        result = self._auth_service.upload_profile_photo(
            request.user,
            fileobj=upload,
            filename=upload.name,
            content_type=upload.content_type,
        )
        if result.failed:
            return service_failure_response(result)
        return Response(UserSerializer(result.data).data)


class CompleteOnboardingView(APIView):
    """POST /users/me/complete-onboarding — mark onboarding complete."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._auth_service = AuthService()

    @extend_schema(request=None, responses=UserSerializer)
    def post(self, request: Request) -> Response:
        result = self._auth_service.complete_onboarding(request.user)
        if result.failed:
            return service_failure_response(result)
        return Response(UserSerializer(result.data).data)
