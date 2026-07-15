"""
Test settings.

Self-contained so the suite runs with no ``.env`` (CI-friendly): a fixed
insecure secret key, SQLite, in-memory cache/channel layer (inherited from base
when REDIS_URL is unset), fast password hashing, and eager Celery so any
enqueued task runs inline instead of contacting a broker.

This changes only the test environment — never application behavior.
"""

from __future__ import annotations

import os

# Populate the few env-required values before base reads them.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-insecure-secret-key")
os.environ.setdefault("DJANGO_DEBUG", "False")

from .base import *  # noqa: E402,F401,F403

# Fast, insecure password hashing for tests (Django admin auth only).
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Run Celery tasks synchronously and surface their errors.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
