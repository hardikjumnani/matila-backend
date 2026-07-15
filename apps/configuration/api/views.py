"""Configuration API views."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.configuration.services.configuration_service import ConfigurationService


class ConfigView(APIView):
    """GET /config — runtime configuration for the client.

    Public (AllowAny): the client needs feature flags, pricing, the minimum
    supported version, and support info at startup, potentially before the user
    authenticates. The payload contains no user-specific or sensitive data.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config = ConfigurationService()

    @extend_schema(responses=dict, description="Get complete runtime configuration.")
    def get(self, request: Request) -> Response:
        return Response(self._config.get_runtime_config())
