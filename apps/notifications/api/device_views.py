"""Device-token registration API views (/users/me/devices)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.responses import service_failure_response
from apps.notifications.api.device_serializers import (
    DeviceRegisterSerializer,
    DeviceTokenSerializer,
)
from apps.notifications.services.device_token_service import DeviceTokenService


class DeviceRegisterView(APIView):
    """POST /users/me/devices — register or rotate a device's FCM token."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = DeviceTokenService()

    @extend_schema(request=DeviceRegisterSerializer, responses=DeviceTokenSerializer)
    def post(self, request: Request) -> Response:
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = self.service.register(
            user=request.user,
            token=data["token"],
            device_id=data["device_id"],
            platform=data["platform"],
            app_version=data["app_version"],
        )
        if result.failed:
            return service_failure_response(result)
        return Response(DeviceTokenSerializer(result.data).data, status=201)


class DeviceLogoutView(APIView):
    """DELETE /users/me/devices/{device_id} — per-device logout."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = DeviceTokenService()

    @extend_schema(responses=OpenApiResponse(description="Device deactivated."))
    def delete(self, request: Request, device_id: str) -> Response:
        result = self.service.deactivate_device(user=request.user, device_id=device_id)
        if result.failed:
            return service_failure_response(result)
        return Response({"deactivated": True})
