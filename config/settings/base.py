"""
Base Django settings shared across all environments.

Environment-specific settings modules (``development``, ``production``) import
everything from this module and override only what differs. Secrets and
environment-dependent values are read through ``python-decouple`` so that no
sensitive value is ever hard-coded in the codebase.

Step 1 establishes a runnable skeleton. Step 2 (Environment & Configuration
Setup) expands the integration-specific sections (Firebase, AWS S3, Razorpay,
Celery, CORS/CSRF) that are intentionally left minimal here.
"""

from __future__ import annotations

from pathlib import Path

import dj_database_url
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
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
# Authentication classes, permission defaults, and the custom exception handler
# are wired in later steps (Step 4 authentication, Step 6 REST APIs). The schema
# generator is set now so documentation is available from the start.
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "UNAUTHENTICATED_USER": None,
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
                "%(asctime)s [%(levelname)s] %(name)s "
                "%(module)s.%(funcName)s:%(lineno)d %(message)s"
            ),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
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
    },
}
