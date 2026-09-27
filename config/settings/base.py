"""
Base Django settings shared across all environments.

Environment-specific settings modules (``development``, ``production``) import
everything from this module and override only what differs. Secrets and
environment-dependent values are read through ``python-decouple`` so that no
sensitive value is ever hard-coded in the codebase.

This module holds configuration common to every environment: database, cache,
channel layer, Celery, storage, and the external integrations (Firebase, Azure
Blob Storage, Razorpay, CORS/CSRF). Credentials and endpoints are read from the
environment; the settings themselves are safe to commit. Environment-specific
hardening and overrides live in ``development`` and ``production``.
"""

from __future__ import annotations

from pathlib import Path

import dj_database_url
from celery.schedules import crontab
from decouple import Csv, config

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# BASE_DIR points at the repository root (the directory containing manage.py).
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Core security
# ---------------------------------------------------------------------------
# SECRET_KEY has no default: every environment must supply it explicitly.
# A missing key must fail loudly rather than silently fall back to an insecure
# value. Local development supplies it via the .env file.
SECRET_KEY: str = config("DJANGO_SECRET_KEY")

# DEBUG defaults to False. Only the development settings module enables it.
DEBUG: bool = config("DJANGO_DEBUG", default=False, cast=bool)

ALLOWED_HOSTS: list[str] = config(
    "DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv()
)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "daphne",  # Must precede staticfiles so runserver uses the ASGI server.
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "channels",
    "corsheaders",
    "drf_spectacular",
]

# Local domain apps. Each app owns a single bounded context as defined in
# DOMAIN_SERVICES.md. The messaging app is deliberately named "apps.messaging"
# (label "messaging") to avoid colliding with django.contrib.messages, which
# already claims the "messages" app label.
LOCAL_APPS = [
    "apps.common",
    "apps.users",
    "apps.verification",
    "apps.matchmaking",
    "apps.chats",
    "apps.messaging",
    "apps.reveal",
    "apps.payments",
    "apps.reports",
    "apps.ratings",
    "apps.notifications",
    "apps.configuration",
    "apps.audit",
    "apps.admin_panel",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Bind a correlation id early so it is available to everything downstream.
    "apps.common.request_id.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Two application entrypoints:
#   - WSGI  serves the synchronous REST API (Gunicorn in production).
#   - ASGI  serves WebSockets and async traffic (Daphne in production).
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# PostgreSQL is the production database. The connection is configured through a
# single DATABASE_URL. A local SQLite fallback keeps management commands such as
# `check` runnable before a database is provisioned; production must always
# supply a PostgreSQL URL (enforced in the production settings module).
DATABASES = {
    "default": dj_database_url.parse(
        config("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=config("DB_CONN_MAX_AGE", default=60, cast=int),
        conn_health_checks=True,
    )
}


# ---------------------------------------------------------------------------
# Channels / Redis channel layer
# ---------------------------------------------------------------------------
# Redis is the channel layer backend in every real environment. An in-memory
# fallback is used only when REDIS_URL is unset (e.g. isolated unit tests), and
# must never be used in production (single-process only).
REDIS_URL: str = config("REDIS_URL", default="")

if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
# Redis is the cache backend for frequently accessed runtime configuration and
# feature flags (ConfigurationService, Step 5). A local-memory fallback keeps
# the cache API usable when REDIS_URL is unset; it is per-process and must not
# be relied upon in production.
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "adc",  # Namespaces keys so cache/channel/broker DBs
            # can safely share a Redis instance.
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }


# ---------------------------------------------------------------------------
# Authentication / password validation
# ---------------------------------------------------------------------------
# Password validators apply only to the Django admin (django.contrib.auth.User).
# Application users authenticate through Firebase; their identity lives in the
# domain `users.User` model, which is intentionally NOT the Django auth user.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Internationalization / time
# ---------------------------------------------------------------------------
# All timestamps are stored and handled in UTC per the frozen schema rules.
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static & media files / object storage
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# User-uploaded media (profile photos, college IDs, gesture selfies, chat
# images) lives in Azure Blob Storage in every real environment. All such media
# is PRIVATE: the container is not public and reads are granted through
# short-lived SAS URLs, because verification documents and view-once images must
# not be world-readable. Media is accessed via StorageService (not Django's
# FileField), so the default file storage below is only a local-dev convenience.
AZURE_STORAGE_CONNECTION_STRING: str = config(
    "AZURE_STORAGE_CONNECTION_STRING", default=""
)
AZURE_STORAGE_CONTAINER: str = config("AZURE_STORAGE_CONTAINER", default="media")
AZURE_SAS_EXPIRY_SECONDS: int = config(
    "AZURE_SAS_EXPIRY_SECONDS", default=3600, cast=int
)
USE_AZURE_BLOB: bool = bool(AZURE_STORAGE_CONNECTION_STRING)

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Upload ceilings — reject oversized request bodies before they are buffered
# into memory, as a first-line abuse/DoS guard on the image upload endpoints.
# The per-media-type limits are enforced in the upload services (Step 5/6).
DATA_UPLOAD_MAX_MEMORY_SIZE = config(
    "DATA_UPLOAD_MAX_MEMORY_SIZE", default=10 * 1024 * 1024, cast=int  # 10 MB
)
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
# Authentication classes, permission defaults, and the custom exception handler
# are wired in later steps (Step 4 authentication, Step 6 REST APIs). The schema
# generator is set now so documentation is available from the start.
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.users.authentication.FirebaseAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Anonymous requests resolve request.user to None (not a Django AnonymousUser)
    # since application users are the Firebase-backed domain model.
    "UNAUTHENTICATED_USER": None,
    # Every response is wrapped in the standard envelope; every error flows
    # through the standard error handler.
    "DEFAULT_RENDERER_CLASSES": [
        "apps.common.api.renderers.EnvelopeJSONRenderer",
    ],
    "EXCEPTION_HANDLER": "apps.common.api.exception_handler.custom_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.common.api.pagination.StandardCursorPagination",
    "PAGE_SIZE": 20,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Anonymous Delayed Chat API",
    "DESCRIPTION": "Backend API for the Anonymous Delayed Chat application.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# A single console handler with a structured, greppable format. Application code
# obtains loggers via `logging.getLogger(__name__)`; the `apps` logger captures
# all domain logging under one namespace.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": (
                "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s "
                "%(module)s.%(funcName)s:%(lineno)d %(message)s"
            ),
        },
    },
    "filters": {
        "request_id": {
            "()": "apps.common.request_id.RequestIDLogFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_id"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": config("DJANGO_LOG_LEVEL", default="INFO"),
    },
    "loggers": {
        "apps": {
            "handlers": ["console"],
            "level": config("APP_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        # The Azure SDK logs full request/response at INFO — far too verbose.
        "azure": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}


# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
# Broker and result backend default to the shared Redis instance. Serialization
# is JSON-only (never pickle) to avoid arbitrary code execution from task
# payloads. The Beat schedule is defined in Step 8 (Background Jobs).
CELERY_BROKER_URL: str = config(
    "CELERY_BROKER_URL", default=REDIS_URL or "redis://localhost:6379/0"
)
CELERY_RESULT_BACKEND: str = config("CELERY_RESULT_BACKEND", default=CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
# Hard/soft time limits bound runaway tasks; individual tasks may override.
CELERY_TASK_TIME_LIMIT = config("CELERY_TASK_TIME_LIMIT", default=300, cast=int)
CELERY_TASK_SOFT_TIME_LIMIT = config(
    "CELERY_TASK_SOFT_TIME_LIMIT", default=270, cast=int
)
# Keep workers connecting through a broker restart (common during deploys).
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# ---------------------------------------------------------------------------
# Development timing overrides (time-compression)
# ---------------------------------------------------------------------------
# All default to 0 / production values, so the FROZEN product timings (72h chat
# window, 24h reveal eligibility, 5-min expiry poll) apply unless explicitly
# overridden — which only ever happens in local dev. Setting a *_SECONDS var to
# a positive value shrinks that part of the lifecycle to seconds for live
# end-to-end testing; EXPIRE_CHATS_INTERVAL_SECONDS speeds the expiry poll to
# match. Consumed in apps.chats.services.chat_service and apps.reveal.services.
CHAT_ANONYMOUS_WINDOW_SECONDS_OVERRIDE: int = config(
    "CHAT_ANONYMOUS_WINDOW_SECONDS", default=0, cast=int
)
CHAT_EXTENSION_WINDOW_SECONDS_OVERRIDE: int = config(
    "CHAT_EXTENSION_WINDOW_SECONDS", default=0, cast=int
)
REVEAL_ELIGIBILITY_SECONDS_OVERRIDE: int = config(
    "REVEAL_ELIGIBILITY_SECONDS", default=0, cast=int
)
# Post-expiry decision grace (24h) before auto-exit; overridable for testing.
DECISION_GRACE_SECONDS_OVERRIDE: int = config(
    "DECISION_GRACE_SECONDS", default=0, cast=int
)
EXPIRE_CHATS_INTERVAL_SECONDS: float = config(
    "EXPIRE_CHATS_INTERVAL_SECONDS", default=300.0, cast=float
)

# Scheduled (Celery Beat) tasks. Asynchronous tasks (push delivery) are enqueued
# on demand and are not listed here.
CELERY_BEAT_SCHEDULE = {
    "expire-chats": {
        "task": "apps.chats.tasks.expire_chats",
        "schedule": EXPIRE_CHATS_INTERVAL_SECONDS,  # 5 min in prod; dev may shrink
    },
    "auto-exit-stale-decisions": {
        "task": "apps.reveal.tasks.auto_exit_stale_decisions",
        "schedule": EXPIRE_CHATS_INTERVAL_SECONDS,  # same cadence as expiry
    },
    "cleanup-expired-media": {
        "task": "apps.messaging.tasks.cleanup_expired_media",
        "schedule": crontab(hour=2, minute=0),  # daily at 02:00 UTC
    },
    "cleanup-stale-match-queue": {
        "task": "apps.matchmaking.tasks.cleanup_stale_match_queue",
        "schedule": 120.0,  # every 2 minutes
    },
    "refresh-configuration-cache": {
        "task": "apps.configuration.tasks.refresh_configuration_cache",
        "schedule": 600.0,  # every 10 minutes
    },
    "sample-system-metrics": {
        "task": "apps.common.tasks.sample_system_metrics",
        "schedule": 300.0,  # every 5 minutes
    },
}


# ---------------------------------------------------------------------------
# Firebase Admin SDK
# ---------------------------------------------------------------------------
# Server-side verification of Firebase ID tokens and FCM HTTP v1 push delivery
# both use the Firebase Admin SDK with a service-account credentials file. The
# SDK is initialized in Step 4; this only records where the credentials live.
#
# NOTE: The legacy FCM server key (FCM_SERVER_KEY) is intentionally NOT used —
# Google shut down the legacy FCM API in June 2024. Push notifications are sent
# via firebase_admin.messaging using these same credentials.
FIREBASE_CREDENTIALS_PATH: str = config("FIREBASE_CREDENTIALS_PATH", default="")
# Clock-skew tolerance (seconds, 0-60) for ID-token verification. Small default
# for production; raise locally if the dev machine's clock cannot reach NTP.
FIREBASE_TOKEN_CLOCK_SKEW_SECONDS: int = config(
    "FIREBASE_TOKEN_CLOCK_SKEW_SECONDS", default=10, cast=int
)


# ---------------------------------------------------------------------------
# Razorpay
# ---------------------------------------------------------------------------
# Payment order creation, client-side verification, and webhook signature
# validation. The webhook secret is separate from the API key secret and is
# configured in the Razorpay dashboard. Client initialization is in Step 5.
RAZORPAY_KEY_ID: str = config("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET: str = config("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET: str = config("RAZORPAY_WEBHOOK_SECRET", default="")

# Google Play Billing is the primary provider for the Android app: reveal and
# extension are *digital in-app purchases*, which Play policy requires be sold via
# Play Billing. The client buys with the Play SDK and posts the purchase token; the
# backend verifies it against the Google Play Developer API with a service-account
# key. ``PAYMENT_PROVIDER`` selects the active provider (Razorpay stays parked for
# web/other platforms).
PAYMENT_PROVIDER: str = config("PAYMENT_PROVIDER", default="google_play")
GOOGLE_PLAY_PACKAGE_NAME: str = config("GOOGLE_PLAY_PACKAGE_NAME", default="")
GOOGLE_PLAY_SERVICE_ACCOUNT_PATH: str = config(
    "GOOGLE_PLAY_SERVICE_ACCOUNT_PATH", default=""
)

# Development-only escape hatch: when enabled, the payment service skips the
# Razorpay gateway entirely (no order created upstream, no signature verified)
# and drives the same reveal/extension side effects directly. The create-order
# response advertises this via ``dev_bypass: true`` so the client can skip the
# checkout SDK. MUST default to False so production always uses the real gateway;
# it is turned on only in the development settings module.
PAYMENTS_DEV_BYPASS: bool = config("PAYMENTS_DEV_BYPASS", default=False, cast=bool)


# ---------------------------------------------------------------------------
# CORS / CSRF
# ---------------------------------------------------------------------------
# The Flutter client is a native app and does not rely on cookies, but explicit
# origins are still configured for the browsable API, admin, and any web
# tooling. Development relaxes this (see the development settings module);
# production supplies an explicit allow-list.
CORS_ALLOWED_ORIGINS: list[str] = config("CORS_ALLOWED_ORIGINS", default="", cast=Csv())
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS: list[str] = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())


# ---------------------------------------------------------------------------
# Admin access
# ---------------------------------------------------------------------------
# Admins are ordinary Firebase-authenticated users whose college email is on
# this allow-list. This keeps a single authentication system (no separate admin
# accounts) and is sufficient at the single-college scale. Matching is
# case-insensitive (see apps.admin_panel.permissions.IsAdminUser).
ADMIN_EMAILS: list[str] = config("ADMIN_EMAILS", default="", cast=Csv())
