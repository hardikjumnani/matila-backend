"""
Shared helpers for the dev-only test-harness management commands.

These commands exist purely to drive local end-to-end testing (seed a partner,
approve verification, send messages as the partner, force expiry). They are
gated on ``DEBUG`` so they can never run against a production settings module.
Modules prefixed with ``_`` are ignored by Django's command discovery.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import CommandError

from apps.users.models import User


def ensure_dev() -> None:
    """Refuse to run unless DEBUG is on (dev/local only)."""
    if not settings.DEBUG:
        raise CommandError(
            "Refusing to run a dev-only harness command with DEBUG=False."
        )


def get_user(email: str) -> User:
    """Look up a user by college email or raise a clear CommandError."""
    user = User.objects.filter(college_email__iexact=email).first()
    if user is None:
        raise CommandError(f"No user with college_email={email!r}.")
    return user
