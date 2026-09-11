"""
Google Play Developer API integration for verifying in-app purchases.

The single seam between the application and Google Play. A service-account key
(configured in settings) authorises calls to the Android Publisher API; the
purchase token the client reports is verified server-side before any entitlement
is granted. Uses ``google-auth`` (already present) + a REST call — no client
discovery document is fetched. Tests mock ``verify_product_purchase``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
# Google Play productPurchase.purchaseState: 0 = purchased, 1 = canceled, 2 = pending.
_PURCHASED = 0

_lock = threading.Lock()
_session = None  # google.auth.transport.requests.AuthorizedSession


class PlayGatewayError(Exception):
    """Base class for Google Play verification failures (transient/config)."""


class InvalidPurchase(PlayGatewayError):
    """The purchase token is unknown or not in a PURCHASED state."""


def _get_session():
    global _session
    if _session is not None:
        return _session
    with _lock:
        if _session is None:
            path = settings.GOOGLE_PLAY_SERVICE_ACCOUNT_PATH
            if not path:
                raise PlayGatewayError("Google Play service account is not configured.")
            # Imported lazily so importing this module performs no I/O.
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_file(
                path, scopes=[_SCOPE]
            )
            _session = AuthorizedSession(credentials)
    return _session


def verify_product_purchase(*, product_id: str, purchase_token: str) -> dict[str, Any]:
    """Verify a one-time product purchase against Google Play.

    Returns the ``productPurchase`` resource on success. Raises ``InvalidPurchase``
    when the token is unknown or not PURCHASED, and ``PlayGatewayError`` on config
    or transport failures.
    """
    package = settings.GOOGLE_PLAY_PACKAGE_NAME
    if not package:
        raise PlayGatewayError("Google Play package name is not configured.")

    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/"
        f"{package}/purchases/products/{product_id}/tokens/{purchase_token}"
    )
    try:
        response = _get_session().get(url, timeout=15)
    except PlayGatewayError:
        raise
    except Exception as exc:  # network / auth errors
        logger.error("Play verification request failed: %s", exc)
        raise PlayGatewayError("Play verification request failed.") from exc

    if response.status_code == 404:
        raise InvalidPurchase("Purchase token not found for this product.")
    if response.status_code != 200:
        logger.error(
            "Play verification HTTP %s: %s", response.status_code, response.text[:300]
        )
        raise PlayGatewayError(f"Play verification returned HTTP {response.status_code}.")

    data = response.json()
    if data.get("purchaseState", 1) != _PURCHASED:
        raise InvalidPurchase(
            f"Purchase not in PURCHASED state (purchaseState={data.get('purchaseState')})."
        )
    return data
