"""
Admin authorization.

Admins are Firebase-authenticated application users whose college email is on
the ``ADMIN_EMAILS`` allow-list. This reuses the single authentication system
rather than maintaining separate admin accounts. Account-status gating (banned/
suspended denied) is already enforced by the authentication layer.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class IsAdminUser(BasePermission):
    """Allow only users whose college email is configured as an admin."""

    code = "FORBIDDEN"
    message = "Administrator access is required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.college_email):
            return False
        allowed = {email.strip().lower() for email in settings.ADMIN_EMAILS}
        return user.college_email.lower() in allowed
