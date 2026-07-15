"""
Permission classes for onboarding- and verification-gated endpoints.

These build on top of authentication (which already guarantees an active,
authenticated user). Admin (`IsAdminUser`, Step 9) and chat-participant
(`IsChatParticipant`, Step 6) permissions are implemented alongside the
endpoints that require them.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.users.enums import VerificationStatus


class IsOnboardingCompleted(BasePermission):
    """Allow only users who have completed onboarding."""

    code = "ONBOARDING_INCOMPLETE"
    message = "You must complete onboarding first."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(
            user and user.is_authenticated and user.onboarding_completed_at is not None
        )


class IsVerifiedUser(BasePermission):
    """Allow only users whose identity verification has been approved."""

    code = "VERIFICATION_REQUIRED"
    message = "Your account must be verified to perform this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.verification_status == VerificationStatus.APPROVED
        )
