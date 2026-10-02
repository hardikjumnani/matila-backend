"""
Verification API views.

All endpoints require a completed onboarding (verification is the step after
onboarding). Views delegate to VerificationService and shape responses; the
service owns the draft/attempt lifecycle and all validation.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api.serializers import ImageUploadSerializer
from apps.common.responses import service_failure_response
from apps.users.permissions import IsOnboardingCompleted
from apps.verification.api.serializers import VerificationRequestSerializer
from apps.verification.services.verification_service import VerificationService


class _VerificationBaseView(APIView):
    permission_classes = [IsAuthenticated, IsOnboardingCompleted]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = VerificationService()


class VerificationStatusView(_VerificationBaseView):
    """GET /verification/status — current status and latest attempt."""

    @extend_schema(responses=VerificationRequestSerializer)
    def get(self, request: Request) -> Response:
        status = self.service.get_status(request.user)
        latest = status["latest_request"]
        return Response(
            {
                "verification_status": status["verification_status"],
                "latest_request": (
                    VerificationRequestSerializer(latest).data if latest else None
                ),
                # College + launch state drive the "verified — launching in ⏳"
                # countdown the client shows while waiting for launch.
                "college": status["college"],
                "launched": status["launched"],
            }
        )


class VerificationGestureView(_VerificationBaseView):
    """GET /verification/gesture — assign and return a random gesture."""

    @extend_schema(
        responses=OpenApiResponse(description="The assigned gesture instruction.")
    )
    def get(self, request: Request) -> Response:
        result = self.service.generate_gesture(request.user)
        if result.failed:
            return service_failure_response(result)
        return Response({"gesture": result.data})


class UploadCollegeIdView(_VerificationBaseView):
    """POST /verification/upload-college-id."""

    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        request=ImageUploadSerializer, responses=VerificationRequestSerializer
    )
    def post(self, request: Request) -> Response:
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        result = self.service.upload_college_id(
            request.user,
            fileobj=upload,
            filename=upload.name,
            content_type=upload.content_type,
        )
        if result.failed:
            return service_failure_response(result)
        return Response(VerificationRequestSerializer(result.data).data)


class UploadGestureSelfieView(_VerificationBaseView):
    """POST /verification/upload-gesture-selfie."""

    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        request=ImageUploadSerializer, responses=VerificationRequestSerializer
    )
    def post(self, request: Request) -> Response:
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        result = self.service.upload_gesture_selfie(
            request.user,
            fileobj=upload,
            filename=upload.name,
            content_type=upload.content_type,
        )
        if result.failed:
            return service_failure_response(result)
        return Response(VerificationRequestSerializer(result.data).data)


class SubmitVerificationView(_VerificationBaseView):
    """POST /verification/submit — finalize the current attempt for review."""

    @extend_schema(request=None, responses=VerificationRequestSerializer)
    def post(self, request: Request) -> Response:
        result = self.service.submit(request.user)
        if result.failed:
            return service_failure_response(result)
        return Response(VerificationRequestSerializer(result.data).data)


class VerificationHistoryView(_VerificationBaseView):
    """GET /verification/history — all previous attempts."""

    @extend_schema(responses=VerificationRequestSerializer(many=True))
    def get(self, request: Request) -> Response:
        history = self.service.get_history(request.user)
        return Response(VerificationRequestSerializer(history, many=True).data)
