"""
Production settings.

Hardens the base configuration and fails fast on misconfiguration. Secrets and
infrastructure endpoints are supplied exclusively through the hosting platform's
environment variables — never committed to the repository.

The remaining production hardening (HSTS tuning, secure cookies, S3 static/media
storage, Sentry) is completed in Step 11 (Deployment & Monitoring).
"""

from __future__ import annotations

from decouple import Csv

from .base import *  # noqa: F401,F403
from .base import DATABASES, REDIS_URL, config

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
    "rest_framework.renderers.JSONRenderer",
]
