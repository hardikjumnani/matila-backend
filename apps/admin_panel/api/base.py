"""Shared base for admin API views."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.admin_panel.permissions import IsAdminUser


class AdminAPIView(APIView):
    """Base view requiring an authenticated admin (ADMIN_EMAILS allow-list)."""

    permission_classes = [IsAuthenticated, IsAdminUser]
