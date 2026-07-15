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
from typing import Any

import firebase_admin
from django.conf import settings
from firebase_admin import auth, credentials

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
