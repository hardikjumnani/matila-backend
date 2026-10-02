"""
DRF authentication for Firebase-issued ID tokens.

Verifies the ``Authorization: Bearer <token>`` header against Firebase and
resolves the corresponding *existing, active* application user. It never creates
users — that happens exclusively in the session bootstrap endpoint — and it
denies non-active accounts globally, so suspended/banned users are rejected on
every protected endpoint regardless of token validity.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from apps.common.firebase import InvalidFirebaseToken, verify_id_token
from apps.users.enums import AccountStatus
from apps.users.models import User
from apps.users.services.auth_service import AuthService

_BEARER_PREFIX = b"bearer"


def extract_bearer_token(request: Request) -> str | None:
    """Return the bearer token from the Authorization header, or ``None``.

    Raises AuthenticationFailed only for a malformed header (a bearer scheme
    with the wrong number of parts). A missing header returns ``None`` so
    endpoints that permit anonymous access still work.
    """
    header = get_authorization_header(request).split()
    if not header or header[0].lower() != _BEARER_PREFIX:
        return None
    if len(header) == 1:
        raise AuthenticationFailed(
            {
                "code": "UNAUTHORIZED",
                "detail": "Invalid Authorization header: no credentials.",
            }
        )
    if len(header) > 2:
        raise AuthenticationFailed(
            {
                "code": "UNAUTHORIZED",
                "detail": "Invalid Authorization header: token contains spaces.",
            }
        )
    return header[1].decode("utf-8", errors="ignore")


class FirebaseAuthentication(BaseAuthentication):
    """Authenticate requests using a Firebase ID token."""

    def __init__(self) -> None:
        self._auth_service = AuthService()

    def authenticate(self, request: Request) -> tuple[User, dict] | None:
        token = extract_bearer_token(request)
        if token is None:
            # No credentials supplied → anonymous; permissions decide access.
            return None

        # Dev-only bypass: a "dev:<email>" token authenticates as that existing
        # user WITHOUT contacting Firebase. Gated on AUTH_DEV_BYPASS, which is
        # False in base + production settings, so this can never run in prod.
        # Used by the local admin panel / harness. See config.settings.development.
        if settings.AUTH_DEV_BYPASS and token.startswith("dev:"):
            email = token[len("dev:") :].strip()
            user = User.objects.filter(college_email__iexact=email).first()
            if user is None:
                raise AuthenticationFailed(
                    {"code": "UNAUTHORIZED", "detail": "Dev bypass: user not found."}
                )
            self._enforce_account_status(user)
            return (user, {"dev_bypass": True, "email": email})

        try:
            claims = verify_id_token(token)
        except InvalidFirebaseToken as exc:
            raise AuthenticationFailed(
                {"code": "UNAUTHORIZED", "detail": "Invalid or expired token."}
            ) from exc

        firebase_uid = claims.get("uid", "")
        user = self._auth_service.get_user_by_firebase_uid(firebase_uid)
        if user is None:
            # Token is valid but the user has not been bootstrapped yet. The
            # client must call the session endpoint first.
            raise AuthenticationFailed(
                {
                    "code": "UNAUTHORIZED",
                    "detail": "No active session. Bootstrap first.",
                }
            )

        self._enforce_account_status(user)
        return (user, claims)

    def _enforce_account_status(self, user: User) -> None:
        """Deny non-active accounts even when the token is valid."""
        if user.account_status == AccountStatus.SUSPENDED:
            raise AuthenticationFailed(
                {"code": "ACCOUNT_SUSPENDED", "detail": "This account is suspended."}
            )
        if user.account_status in (AccountStatus.BANNED, AccountStatus.DELETED):
            raise AuthenticationFailed(
                {"code": "ACCOUNT_BANNED", "detail": "This account is banned."}
            )

    def authenticate_header(self, request: Request) -> str:
        # Drives the WWW-Authenticate header so failures are 401, not 403.
        return "Bearer"
