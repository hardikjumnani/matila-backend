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
    # Google Play billing verification is validated lazily by gateway_play (a
    # service-account credential), not required at startup.
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
# includeSubDomains / preload default OFF: the launch host is an Azure-assigned
# label under the shared *.cloudapp.azure.com parent, which we do not own and
# whose sibling subdomains we must not assert HSTS over. `preload` is also
# effectively irreversible. Enable both via env once on a fully-owned domain.
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool
)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = True

# JSON-only API surface in production (no browsable API).
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "apps.common.api.renderers.EnvelopeJSONRenderer",
]

# --- Error tracking (Sentry) ------------------------------------------------
# Errors only (no performance traces) to stay well inside the free tier. The
# request-id correlation tag is applied automatically by
# apps.common.request_id._tag_sentry once sentry_sdk is importable. PII is off,
# and before_send strips auth headers + any ?token= from URLs (defence in depth,
# matching the token-log hygiene from Phase C).
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    import re

    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    _TOKEN_QS_RE = re.compile(r"(token=)[^&\s]+", re.IGNORECASE)

    def _scrub_sensitive(event, hint):  # noqa: ANN001, ARG001
        request = event.get("request")
        if isinstance(request, dict):
            qs = request.get("query_string")
            if isinstance(qs, str):
                request["query_string"] = _TOKEN_QS_RE.sub(r"\1[Filtered]", qs)
            elif isinstance(qs, list):
                request["query_string"] = [
                    [k, "[Filtered]" if str(k).lower() == "token" else v]
                    for k, v in qs
                ]
            url = request.get("url")
            if isinstance(url, str):
                request["url"] = _TOKEN_QS_RE.sub(r"\1[Filtered]", url)
            headers = request.get("headers")
            if isinstance(headers, dict):
                for name in list(headers):
                    if name.lower() in ("authorization", "cookie"):
                        headers[name] = "[Filtered]"
        return event

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=config("SENTRY_ENVIRONMENT", default="production"),
        integrations=[DjangoIntegration(), CeleryIntegration()],
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=0.0,  # errors only
        before_send=_scrub_sensitive,
    )
