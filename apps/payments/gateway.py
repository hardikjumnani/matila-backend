"""
Razorpay gateway integration.

The single seam between the application and Razorpay. The client is created
lazily from settings so importing this module performs no I/O and tests can mock
these functions. Signatures are ALWAYS verified through the SDK utilities —
never reimplemented — per the frozen payment security rules.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import razorpay
from django.conf import settings
from razorpay.errors import SignatureVerificationError

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_client: razorpay.Client | None = None


class PaymentGatewayError(Exception):
    """Base class for payment gateway failures."""


class InvalidPaymentSignature(PaymentGatewayError):
    """A payment or webhook signature failed verification."""


def _get_client() -> razorpay.Client:
    global _client
    if _client is not None:
        return _client
    with _init_lock:
        if _client is None:
            if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
                raise PaymentGatewayError("Razorpay credentials are not configured.")
            _client = razorpay.Client(
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            )
    return _client


def create_order(
    *,
    amount_in_paise: int,
    currency: str,
    receipt: str,
    notes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a Razorpay order and return its representation."""
    try:
        return _get_client().order.create(
            {
                "amount": amount_in_paise,
                "currency": currency,
                "receipt": receipt,
                "payment_capture": 1,
                "notes": notes or {},
            }
        )
    except PaymentGatewayError:
        raise
    except Exception as exc:  # razorpay raises a range of errors.
        logger.error("Razorpay order creation failed: %s", exc)
        raise PaymentGatewayError("Failed to create payment order.") from exc


def verify_payment_signature(*, order_id: str, payment_id: str, signature: str) -> None:
    """Verify a client-reported payment signature. Raises on mismatch."""
    try:
        _get_client().utility.verify_payment_signature(
            {
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            }
        )
    except SignatureVerificationError as exc:
        raise InvalidPaymentSignature("Payment signature verification failed.") from exc


def verify_webhook_signature(*, body: str, signature: str) -> None:
    """Verify a Razorpay webhook signature. Raises on mismatch."""
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret:
        raise PaymentGatewayError("Razorpay webhook secret is not configured.")
    try:
        _get_client().utility.verify_webhook_signature(body, signature, secret)
    except SignatureVerificationError as exc:
        raise InvalidPaymentSignature("Webhook signature verification failed.") from exc
