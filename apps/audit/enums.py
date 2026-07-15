"""Enumerations owned by the audit domain."""

from __future__ import annotations

from django.db import models


class ActorType(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    USER = "USER", "User"
    SYSTEM = "SYSTEM", "System"
