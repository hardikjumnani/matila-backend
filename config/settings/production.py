"""
Production settings.

Hardens the base configuration and fails fast on misconfiguration. Secrets and
infrastructure endpoints are supplied exclusively through the hosting platform's
environment variables — never committed to the repository.

Remaining operational hardening (HSTS tuning, static-file serving strategy,
Sentry error tracking) is completed in Step 11 (Deployment & Monitoring).
"""

from __future__ import annotations

from decouple import Csv

from .base import *  # noqa: F401,F403
from .base import (
    AZURE_STORAGE_CONNECTION_STRING,
    AZURE_STORAGE_CONTAINER,
    DATABASES,
    FIREBASE_CREDENTIALS_PATH,
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET,
    REDIS_URL,
    config,
)

# DEBUG must always be False in production.
DEBUG = False

# No wildcard hosts in production — the allowed hosts are explicit.
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", cast=Csv())

# --- Fail-fast configuration guards -----------------------------------------
# Production must run on PostgreSQL and a real Redis instance. Silent fallbacks
# (SQLite, in-memory channel layer) are unacceptable and are rejected here.
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise RuntimeError(
        "Production requires a PostgreSQL DATABASE_URL "
        f"(got engine: {DATABASES['default']['ENGINE']!r})."
    )

if not REDIS_URL:
    raise RuntimeError("Production requires REDIS_URL to be configured.")

# Critical integration secrets. Core product flows (authentication, media
# uploads, payments) cannot function without these, so a missing value must
# abort startup rather than surface as a runtime failure under user traffic.
# Feature-flaggable extras are validated lazily by their services instead.
_REQUIRED_SETTINGS = {
    "FIREBASE_CREDENTIALS_PATH": FIREBASE_CREDENTIALS_PATH,  # auth + push
    "AZURE_STORAGE_CONNECTION_STRING": AZURE_STORAGE_CONNECTION_STRING,  # media
    "AZURE_STORAGE_CONTAINER": AZURE_STORAGE_CONTAINER,  # media
    "RAZORPAY_KEY_ID": RAZORPAY_KEY_ID,  # payments
    "RAZORPAY_KEY_SECRET": RAZORPAY_KEY_SECRET,  # payments
    "RAZORPAY_WEBHOOK_SECRET": RAZORPAY_WEBHOOK_SECRET,  # webhook verification
}
_missing = sorted(name for name, value in _REQUIRED_SETTINGS.items() if not value)
if _missing:
    raise RuntimeError(
        "Production is missing required configuration: " + ", ".join(_missing)
    )

# Explicit CORS/CSRF allow-lists are mandatory in production; an empty list
# would silently reject the client rather than fail loudly, so require them.
if not config("CORS_ALLOWED_ORIGINS", default=""):
    raise RuntimeError("Production requires CORS_ALLOWED_ORIGINS to be configured.")

# --- Baseline security hardening --------------------------------------------
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# JSON-only API surface in production (no browsable API).
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "apps.common.api.renderers.EnvelopeJSONRenderer",
]
