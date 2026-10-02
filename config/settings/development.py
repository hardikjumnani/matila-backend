"""
Development settings.

Enables DEBUG, relaxes host checking, and inherits everything else from
``base``. Integration-specific development configuration (Redis, sandbox
credentials) is layered in via the local ``.env`` file.

PostgreSQL is the default development database: local development runs on the
same engine as production so behavior matches. SQLite is no longer used for
development (it remains only as the test-harness default for fast CI).
"""

from __future__ import annotations

import dj_database_url

from .base import *  # noqa: F401,F403
from .base import config

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Default the development database to local PostgreSQL (overridable via
# DATABASE_URL). No SQLite fallback here.
DATABASES = {
    "default": dj_database_url.parse(
        config(
            "DATABASE_URL",
            default="postgres://postgres:postgres@localhost:5432/anonymous_chat",
        ),
        conn_max_age=config("DB_CONN_MAX_AGE", default=60, cast=int),
        conn_health_checks=True,
    )
}

# Browsable API is convenient during local development only. The envelope
# renderer stays first so API responses keep the standard shape.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "apps.common.api.renderers.EnvelopeJSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# Permissive CORS for local Flutter development. Locked down in production.
CORS_ALLOW_ALL_ORIGINS = config("CORS_ALLOW_ALL_ORIGINS", default=True, cast=bool)

# Skip Play purchase-token verification for local end-to-end testing (reveal /
# safe reveal / extension / store complete with placeholder tokens). On by
# default in development; overridable.
PAYMENTS_DEV_BYPASS = config("PAYMENTS_DEV_BYPASS", default=True, cast=bool)

# Accept "dev:<email>" bearer tokens locally (admin panel / harness). Dev only.
AUTH_DEV_BYPASS = config("AUTH_DEV_BYPASS", default=True, cast=bool)
