"""
Development settings.

Enables DEBUG, relaxes host checking, and inherits everything else from
``base``. Integration-specific development configuration (local Redis, local
Postgres, sandbox credentials) is layered in via the local ``.env`` file in
Step 2.
"""

from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import config

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Browsable API is convenient during local development only. The envelope
# renderer stays first so API responses keep the standard shape.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "apps.common.api.renderers.EnvelopeJSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# Permissive CORS for local Flutter development. Locked down in production.
CORS_ALLOW_ALL_ORIGINS = config("CORS_ALLOW_ALL_ORIGINS", default=True, cast=bool)
