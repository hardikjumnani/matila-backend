"""Enumerations owned by the messaging domain."""

from __future__ import annotations

from django.db import models


class MessageType(models.TextChoices):
    TEXT = "TEXT", "Text"
    IMAGE = "IMAGE", "Image"
    SYSTEM = "SYSTEM", "System"


class MediaVisibility(models.TextChoices):
    NORMAL = "NORMAL", "Normal"
    VIEW_ONCE = "VIEW_ONCE", "View once"


class MediaStatus(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    VIEWED = "VIEWED", "Viewed"
    EXPIRED = "EXPIRED", "Expired"
    DELETED = "DELETED", "Deleted"
