"""
Firebase Admin SDK integration.

This module is the single seam between the application and Firebase. The Admin
SDK app is initialized lazily (on first use) from the service-account
credentials configured in settings, so importing this module never performs
I/O and test suites that mock ``verify_id_token`` never touch real credentials.

Tokens are ALWAYS verified through the Admin SDK (``auth.verify_id_token``) —
never decoded manually — per the frozen security rules.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import firebase_admin
from django.conf import settings
from firebase_admin import auth, credentials, messaging

logger = logging.getLogger(__name__)

# Guards one-time initialization of the module-level Firebase app.
_init_lock = threading.Lock()
_firebase_app: firebase_admin.App | None = None


class FirebaseError(Exception):
    """Base class for Firebase integration failures."""


class FirebaseNotConfigured(FirebaseError):
    """The Firebase credentials path is not configured."""


class InvalidFirebaseToken(FirebaseError):
    """The supplied Firebase ID token is missing, malformed, or invalid."""


def _get_app() -> firebase_admin.App:
    """Return the initialized Firebase app, creating it once on first call."""
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    with _init_lock:
        if _firebase_app is None:
            credentials_path = settings.FIREBASE_CREDENTIALS_PATH
            if not credentials_path:
                raise FirebaseNotConfigured(
                    "FIREBASE_CREDENTIALS_PATH is not configured."
                )
            certificate = credentials.Certificate(credentials_path)
            _firebase_app = firebase_admin.initialize_app(certificate)
            logger.info("Firebase Admin SDK initialized.")
    return _firebase_app


def verify_id_token(token: str) -> dict[str, Any]:
    """Verify a Firebase ID token and return its decoded claims.

    Raises:
        InvalidFirebaseToken: if the token is empty or fails verification.
        FirebaseNotConfigured: if Firebase credentials are not configured.
    """
    if not token:
        raise InvalidFirebaseToken("No token supplied.")
    try:
        return auth.verify_id_token(token, app=_get_app())
    except FirebaseNotConfigured:
        raise
    except Exception as exc:  # firebase_admin raises a range of token errors.
        # Log at debug: invalid tokens are an expected, client-driven condition,
        # not a server error. The token itself is never logged.
        logger.debug("Firebase token verification failed: %s", exc)
        raise InvalidFirebaseToken("Firebase token verification failed.") from exc


@dataclass(frozen=True, slots=True)
class PushResult:
    """Outcome of a multicast push, with tokens FCM reported as dead."""

    success_count: int
    failure_count: int
    invalid_tokens: list[str]


# FCM errors that mean a token is permanently dead and should be deactivated.
_DEAD_TOKEN_ERRORS = (
    messaging.UnregisteredError,
    messaging.SenderIdMismatchError,
)


def send_push(
    tokens: list[str],
    *,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> PushResult:
    """Send a notification to many device tokens via FCM (HTTP v1).

    Returns per-batch success/failure counts and the subset of tokens FCM
    reported as invalid/unregistered so the caller can deactivate them. Never
    used with the deprecated legacy server key — this is the Admin SDK path.
    """
    if not tokens:
        return PushResult(success_count=0, failure_count=0, invalid_tokens=[])

    message = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        # FCM data values must be strings.
        data={key: str(value) for key, value in (data or {}).items()},
    )
    response = messaging.send_each_for_multicast(message, app=_get_app())

    invalid_tokens: list[str] = []
    for token, result in zip(tokens, response.responses, strict=False):
        if not result.success and isinstance(result.exception, _DEAD_TOKEN_ERRORS):
            invalid_tokens.append(token)

    return PushResult(
        success_count=response.success_count,
        failure_count=response.failure_count,
        invalid_tokens=invalid_tokens,
    )
